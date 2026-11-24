using System;
using System.Collections.Generic;
using System.Globalization;

namespace CallCenter
{
    /// <summary>Excel(설치 필요)을 COM으로 제어하는 얇은 래퍼. 표(ListObject) 기반 읽기/쓰기를 제공한다.</summary>
    public class ExcelApp : IDisposable
    {
        private object _app;
        private object _workbooks;
        private bool _disposed;

        public ExcelApp()
        {
            Type t = Type.GetTypeFromProgID("Excel.Application");
            if (t == null) throw new InvalidOperationException("Microsoft Excel이 설치되어 있지 않습니다.");
            _app = Activator.CreateInstance(t);
            Late.Set(_app, "DisplayAlerts", false);
            _workbooks = Late.Get(_app, "Workbooks");
        }

        public void SetVisible(bool visible) { Late.Set(_app, "Visible", visible); }

        public object OpenWorkbook(string path, bool readOnly)
        {
            return Late.Call(_workbooks, "Open", path, Type.Missing, readOnly);
        }

        public object GetSheet(object wb, string name)
        {
            return Late.Get(Late.Get(wb, "Worksheets"), "Item", name);
        }

        public object GetTable(object ws, string name)
        {
            return Late.Get(Late.Get(ws, "ListObjects"), "Item", name);
        }

        public void CloseWorkbook(object wb, bool save) { Late.Call(wb, "Close", save); }
        public void Save(object wb) { Late.Call(wb, "Save"); }
        public void RefreshAll(object wb) { Late.Call(wb, "RefreshAll"); }

        public static string ToStr(object o)
        {
            if (o == null) return "";
            if (o is double) return ((double)o).ToString("R", CultureInfo.InvariantCulture);
            return Convert.ToString(o, CultureInfo.InvariantCulture) ?? "";
        }

        /// <summary>시트의 사용 영역을 첫 행=머리글인 표로 읽는다. 완전히 빈 행은 건너뛴다.</summary>
        public List<Dictionary<string, string>> ReadTable(object ws)
        {
            var rows = new List<Dictionary<string, string>>();
            object used = Late.Get(ws, "UsedRange");
            object v = Late.Get(used, "Value2");
            object[,] arr = v as object[,];
            if (arr == null) return rows;
            int r0 = arr.GetLowerBound(0), r1 = arr.GetUpperBound(0);
            int c0 = arr.GetLowerBound(1), c1 = arr.GetUpperBound(1);
            var headers = new List<string>();
            for (int c = c0; c <= c1; c++) headers.Add(ToStr(arr[r0, c]).Trim());
            for (int r = r0 + 1; r <= r1; r++)
            {
                var d = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                bool any = false;
                for (int c = c0; c <= c1; c++)
                {
                    string s = ToStr(arr[r, c]);
                    if (s.Length > 0) any = true;
                    string h = headers[c - c0];
                    if (h.Length > 0) d[h] = s;
                }
                if (any) rows.Add(d);
            }
            return rows;
        }

        // ---- 표(ListObject) 도우미 ----

        public List<string> TableColumns(object lo)
        {
            var names = new List<string>();
            object lc = Late.Get(lo, "ListColumns");
            int n = Convert.ToInt32(Late.Get(lc, "Count"));
            for (int i = 1; i <= n; i++)
            {
                object col = Late.Get(lc, "Item", i);
                names.Add(Convert.ToString(Late.Get(col, "Name")));
            }
            return names;
        }

        /// <summary>표의 첫 번째 열이 시트에서 몇 번째 열인지.</summary>
        public int TableFirstColumn(object lo)
        {
            return Convert.ToInt32(Late.Get(Late.Get(lo, "Range"), "Column"));
        }

        public int DataRowCount(object lo)
        {
            return Convert.ToInt32(Late.Get(Late.Get(lo, "ListRows"), "Count"));
        }

        /// <summary>표의 특정 열(1부터) 데이터 값을 읽는다. firstSheetRow는 첫 데이터 행의 시트 행 번호.</summary>
        public List<string> ReadColumnValues(object lo, int colIdx, out int firstSheetRow)
        {
            var list = new List<string>();
            firstSheetRow = 0;
            if (DataRowCount(lo) == 0) return list;
            object col = Late.Get(Late.Get(lo, "ListColumns"), "Item", colIdx);
            object rng = Late.Get(col, "DataBodyRange");
            if (rng == null) return list;
            firstSheetRow = Convert.ToInt32(Late.Get(rng, "Row"));
            object v = Late.Get(rng, "Value2");
            object[,] arr = v as object[,];
            if (arr != null)
            {
                for (int r = arr.GetLowerBound(0); r <= arr.GetUpperBound(0); r++) list.Add(ToStr(arr[r, arr.GetLowerBound(1)]));
            }
            else
            {
                list.Add(ToStr(v));
            }
            return list;
        }

        /// <summary>표 끝에 새 행을 추가하고 시트 행 번호를 돌려준다(계산 열 수식은 표가 자동으로 채움).</summary>
        public int AddRow(object lo)
        {
            object lr = Late.Call(Late.Get(lo, "ListRows"), "Add");
            return Convert.ToInt32(Late.Get(Late.Get(lr, "Range"), "Row"));
        }

        public void WriteCell(object ws, int row, int col, object value, bool asText)
        {
            object cell = Late.Get(Late.Get(ws, "Cells"), "Item", row, col);
            if (value == null)
            {
                Late.Call(cell, "ClearContents");
                return;
            }
            if (asText)
            {
                Late.Set(cell, "NumberFormat", "@");
                string s = Convert.ToString(value, CultureInfo.InvariantCulture);
                // 수식으로 해석되는 것을 막는다.
                if (s.StartsWith("=") || s.StartsWith("+") || s.StartsWith("-") || s.StartsWith("@")) s = "'" + s;
                Late.Set(cell, "Value2", s);
            }
            else
            {
                Late.Set(cell, "Value2", value);
            }
        }

        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            try { Late.Call(_app, "Quit"); } catch (Exception) { }
            Late.Release(_workbooks);
            Late.Release(_app);
            _workbooks = null;
            _app = null;
        }
    }
}
