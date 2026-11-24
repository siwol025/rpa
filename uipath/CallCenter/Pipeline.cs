using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace CallCenter
{
    public class RunResult
    {
        public int Total;
        public int RowsAdded;
        public int RowsUpdated;
        public int ErrorRows;
        public int MovedToProcessed;
        public int MovedToError;
        public int SystemErrors;

        public string Summary()
        {
            return string.Format(
                "처리 파일 {0}건 | 본시트 추가 {1}, 갱신 {2} | 예외시트 {3} | processed {4}, error {5} | 시스템 오류 {6}",
                Total, RowsAdded, RowsUpdated, ErrorRows, MovedToProcessed, MovedToError, SystemErrors);
        }
    }

    public class OutCell
    {
        public string Column;
        public object Value;
        public bool IsText;
    }

    /// <summary>
    /// 1단계: {ResultInputFolder}/*.json 을 읽어 검증·매핑 후 엑셀 보고서에 upsert 한다.
    /// UiPath 의존성이 없어 단독 테스트가 가능하다.
    /// </summary>
    public class Pipeline
    {
        private readonly Action<string, string> _log;

        public Pipeline(Action<string, string> log)
        {
            _log = log ?? delegate (string level, string msg) { };
        }

        private void Info(string msg) { _log("Info", msg); }
        private void Warn(string msg) { _log("Warn", msg); }
        private void Error(string msg) { _log("Error", msg); }

        public static string ResolveConfigPath(string configPath)
        {
            var tried = new List<string>();
            var candidates = new List<string>();
            if (!string.IsNullOrWhiteSpace(configPath)) candidates.Add(configPath);
            candidates.Add(Path.Combine(Environment.CurrentDirectory, "Data", "Config.xlsx"));
            candidates.Add(Path.Combine(AppContext.BaseDirectory, "Data", "Config.xlsx"));
            foreach (string c in candidates)
            {
                string full = Path.GetFullPath(c);
                tried.Add(full);
                if (File.Exists(full)) return full;
            }
            throw new FileNotFoundException("Config.xlsx를 찾을 수 없습니다. 시도한 경로: " + string.Join(" | ", tried));
        }

        public RunResult Run(string configPath, IDictionary<string, string> overrides)
        {
            var result = new RunResult();
            string cfgPath = ResolveConfigPath(configPath);
            // 상대 경로는 프로젝트 루트(= Data 폴더의 부모) 기준
            string cfgDir = Path.GetDirectoryName(cfgPath);
            string baseDir = string.Equals(Path.GetFileName(cfgDir), "Data", StringComparison.OrdinalIgnoreCase)
                ? Path.GetDirectoryName(cfgDir) : cfgDir;

            using (var xl = new ExcelApp())
            {
                AppConfig cfg = AppConfig.Load(xl, cfgPath, overrides);
                xl.SetVisible(IsTrue(cfg.Setting("ExcelVisible")));
                Info("Config 로드 완료: " + cfgPath);

                string inDir = Req(cfg, baseDir, "ResultInputFolder");
                string processedDir = Req(cfg, baseDir, "ResultProcessedFolder");
                string errorDir = Req(cfg, baseDir, "ResultErrorFolder");
                string reportPath = Req(cfg, baseDir, "ExcelReportPath");
                string pattern = cfg.Setting("ResultFilePattern");
                if (pattern.Length == 0) pattern = "*.json";

                Directory.CreateDirectory(inDir);
                Directory.CreateDirectory(processedDir);
                Directory.CreateDirectory(errorDir);
                EnsureReport(cfg, baseDir, reportPath);

                string[] files = Directory.GetFiles(inDir, pattern);
                Array.Sort(files, StringComparer.OrdinalIgnoreCase);
                Info("대상 JSON " + files.Length + "건 (" + inDir + ")");
                if (files.Length == 0) return result;

                object wb = xl.OpenWorkbook(reportPath, false);
                try
                {
                    object wsCalls = xl.GetSheet(wb, cfg.Setting("ExcelCallSheet"));
                    object loCalls = xl.GetTable(wsCalls, cfg.Setting("ExcelCallTable"));
                    object wsErr = xl.GetSheet(wb, cfg.Setting("ExcelErrorSheet"));
                    object loErr = xl.GetTable(wsErr, cfg.Setting("ExcelErrorTable"));

                    foreach (string file in files)
                    {
                        result.Total++;
                        string name = Path.GetFileName(file);
                        try
                        {
                            string outcome = ProcessFile(xl, cfg, file, wsCalls, loCalls, wsErr, loErr, result);
                            MoveUnique(file, processedDir);
                            result.MovedToProcessed++;
                            Info("[OK] " + name + " → " + outcome);
                        }
                        catch (BusinessException bex)
                        {
                            MoveUnique(file, errorDir);
                            result.MovedToError++;
                            Warn("[업무오류] " + name + " → error 폴더: " + bex.Message);
                        }
                        catch (Exception ex)
                        {
                            result.SystemErrors++;
                            Error("[시스템오류] " + name + " (파일은 그대로 둠, 다음 실행에서 재시도): " + ex.Message);
                        }
                    }

                    if (result.RowsAdded + result.RowsUpdated + result.ErrorRows > 0)
                    {
                        if (IsTrue(cfg.Setting("RefreshAllAfterWrite"))) xl.RefreshAll(wb);
                        xl.Save(wb);
                        Info("엑셀 저장 완료: " + reportPath);
                    }
                }
                finally
                {
                    xl.CloseWorkbook(wb, false);
                }
            }
            Info(result.Summary());
            return result;
        }

        // ---------------------------------------------------------------

        private string ProcessFile(ExcelApp xl, AppConfig cfg, string file,
            object wsCalls, object loCalls, object wsErr, object loErr, RunResult result)
        {
            string text = File.ReadAllText(file, Encoding.UTF8);
            using (ResultJson rj = ResultJson.Parse(text))
            {
                string schema = rj.Get("schema_version");
                string expected = cfg.Constant("ResultSchemaVersion");
                if (expected.Length > 0 && schema != expected)
                    throw new BusinessException("스키마 버전 불일치: " + (schema ?? "(없음)") + " (기대 " + expected + ")");

                string callId = rj.Get("call_id");
                if (string.IsNullOrWhiteSpace(callId)) throw new BusinessException("필수값 누락: call_id");

                string status = rj.Get("status");
                if (status != cfg.Constant("StatusSuccess") && status != cfg.Constant("StatusNeedsReview") && status != cfg.Constant("StatusFailed"))
                    throw new BusinessException("알 수 없는 status: " + (status ?? "(없음)"));

                RouteRow route = cfg.Routing.FirstOrDefault(r => r.Status == status);
                if (route == null) throw new BusinessException("Routing 정의 없음: " + status);

                bool failed = status == cfg.Constant("StatusFailed");
                List<MapRow> map = failed ? cfg.ErrorMap : cfg.ColumnMap;

                if (failed)
                {
                    if (string.IsNullOrWhiteSpace(rj.Get("error.stage")) || string.IsNullOrWhiteSpace(rj.Get("error.reason")))
                        throw new BusinessException("FAILED 건에 error.stage/error.reason 없음");
                }
                else
                {
                    ValidateRequired(map, rj, status);
                }

                List<OutCell> cells = BuildCells(cfg, map, rj);

                string sheetName = cfg.ResolveRef(route.TargetSheet);
                string tableName = cfg.ResolveRef(route.TargetTable);
                object ws = failed ? wsErr : wsCalls;
                object lo = failed ? loErr : loCalls;
                string keyColumn = cfg.Setting("UpsertKeyColumn");
                if (keyColumn.Length == 0) keyColumn = "통화ID";

                string action = Upsert(xl, ws, lo, keyColumn, cells);
                if (failed) result.ErrorRows++;
                else if (action == "추가") result.RowsAdded++;
                else result.RowsUpdated++;
                return sheetName + "/" + tableName + " " + action + " (" + callId + ")";
            }
        }

        private static void ValidateRequired(List<MapRow> map, ResultJson rj, string status)
        {
            foreach (MapRow m in map)
            {
                if (!m.WriteByRobot) continue;
                string req = m.RequiredWhen ?? "";
                if (!req.StartsWith("Y", StringComparison.OrdinalIgnoreCase)) continue;
                bool always = req.Contains("전체");
                // "Y (SUCCESS/NEEDS_REVIEW)" 형태: FAILED가 아닐 때만 필수 (이 메서드는 FAILED에서 호출되지 않음)
                if (!always && status == "FAILED") continue;
                string v = rj.Get(m.JsonPath);
                if (string.IsNullOrWhiteSpace(v)) throw new BusinessException("필수값 누락: " + m.JsonPath + " (" + m.ExcelColumn + ")");
            }
        }

        private List<OutCell> BuildCells(AppConfig cfg, List<MapRow> map, ResultJson rj)
        {
            var cells = new List<OutCell>();
            foreach (MapRow m in map)
            {
                if (!m.WriteByRobot) continue;
                string raw = rj.Get(m.JsonPath);

                // type_label이 비어 있고 type 코드만 있으면 코드로 대체
                if (string.IsNullOrWhiteSpace(raw) && m.JsonPath == "type_label")
                {
                    string code = rj.Get("type");
                    string mapped;
                    if (!string.IsNullOrWhiteSpace(code) && cfg.ValueMap.TryGetValue("type_code|" + code, out mapped)) raw = mapped;
                }

                if (!string.IsNullOrWhiteSpace(raw) && m.Transform.StartsWith("ValueMap:", StringComparison.OrdinalIgnoreCase))
                {
                    string group = m.Transform.Substring("ValueMap:".Length).Trim();
                    string mapped;
                    if (cfg.ValueMap.TryGetValue(group + "|" + raw, out mapped)) raw = mapped;
                    else Warn("ValueMap에 없는 값: " + group + "|" + raw + " (원본 유지)");
                }

                var cell = new OutCell();
                cell.Column = m.ExcelColumn;
                cell.IsText = false;
                if (string.IsNullOrWhiteSpace(raw))
                {
                    cell.Value = null;
                }
                else
                {
                    string dt = m.DataType.ToLowerInvariant();
                    if (dt == "datetime")
                    {
                        // ISO 8601(+09:00) → 시계 시각(KST) 그대로 엑셀 날짜로
                        cell.Value = DateTimeOffset.Parse(raw, CultureInfo.InvariantCulture).DateTime.ToOADate();
                    }
                    else if (dt == "int" || dt == "number")
                    {
                        double d;
                        if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out d)) cell.Value = d;
                        else { cell.Value = raw; cell.IsText = true; }
                    }
                    else
                    {
                        cell.Value = raw;
                        cell.IsText = true;
                    }
                }
                cells.Add(cell);
            }
            return cells;
        }

        private string Upsert(ExcelApp xl, object ws, object lo, string keyColumn, List<OutCell> cells)
        {
            List<string> cols = xl.TableColumns(lo);
            int keyIdx = cols.FindIndex(c => string.Equals(c, keyColumn, StringComparison.OrdinalIgnoreCase)) + 1;
            if (keyIdx <= 0) throw new InvalidOperationException("표에 키 컬럼이 없습니다: " + keyColumn);
            OutCell keyCell = cells.FirstOrDefault(c => string.Equals(c.Column, keyColumn, StringComparison.OrdinalIgnoreCase));
            string key = keyCell == null || keyCell.Value == null ? "" : Convert.ToString(keyCell.Value, CultureInfo.InvariantCulture);
            if (key.Length == 0) throw new BusinessException("키 값(" + keyColumn + ")이 비어 있음");

            int firstRow;
            List<string> keys = xl.ReadColumnValues(lo, keyIdx, out firstRow);
            int row = -1;
            string action;
            for (int i = 0; i < keys.Count; i++)
            {
                if (keys[i] == key) { row = firstRow + i; break; }
            }
            if (row > 0)
            {
                action = "갱신";
            }
            else if (keys.Count == 1 && keys[0].Length == 0)
            {
                // 빈 양식의 비어 있는 첫 행을 재사용
                row = firstRow;
                action = "추가";
            }
            else
            {
                row = xl.AddRow(lo);
                action = "추가";
            }

            int firstCol = xl.TableFirstColumn(lo);
            foreach (OutCell c in cells)
            {
                int idx = cols.FindIndex(n => string.Equals(n, c.Column, StringComparison.OrdinalIgnoreCase)) + 1;
                if (idx <= 0) { Warn("표에 없는 컬럼 건너뜀: " + c.Column); continue; }
                xl.WriteCell(ws, row, firstCol + idx - 1, c.Value, c.IsText);
            }
            return action;
        }

        private void EnsureReport(AppConfig cfg, string baseDir, string reportPath)
        {
            if (File.Exists(reportPath)) return;
            string template = cfg.Setting("ExcelTemplatePath");
            if (template.Length == 0) throw new FileNotFoundException("보고서 파일이 없고 ExcelTemplatePath도 비어 있습니다: " + reportPath);
            if (!Path.IsPathRooted(template)) template = Path.Combine(baseDir, template);
            if (!File.Exists(template)) throw new FileNotFoundException("보고서도 템플릿도 없습니다: " + template);
            Directory.CreateDirectory(Path.GetDirectoryName(reportPath));
            File.Copy(template, reportPath);
            Info("템플릿에서 보고서 생성: " + reportPath);
        }

        private static string Req(AppConfig cfg, string baseDir, string key)
        {
            string v = cfg.Setting(key);
            if (v.Length == 0) throw new InvalidOperationException("Config Settings에 값이 없습니다: " + key);
            return Path.IsPathRooted(v) ? v : Path.GetFullPath(Path.Combine(baseDir, v));
        }

        private static bool IsTrue(string s)
        {
            return string.Equals((s ?? "").Trim(), "true", StringComparison.OrdinalIgnoreCase);
        }

        private static void MoveUnique(string file, string destDir)
        {
            string name = Path.GetFileName(file);
            string dest = Path.Combine(destDir, name);
            if (File.Exists(dest))
            {
                dest = Path.Combine(destDir, Path.GetFileNameWithoutExtension(name) + "_" + DateTime.Now.ToString("yyyyMMddHHmmss") + Path.GetExtension(name));
            }
            File.Move(file, dest);
        }
    }
}
