using System;
using System.Collections.Generic;

namespace CallCenter
{
    public class MapRow
    {
        public int Order;
        public string ExcelColumn = "";
        public string JsonPath = "";
        public string DataType = "string";
        public bool WriteByRobot;
        public string RequiredWhen = "";
        public string Transform = "";
    }

    public class RouteRow
    {
        public string Status = "";
        public string TargetSheet = "";
        public string TargetTable = "";
    }

    /// <summary>Config.xlsx(Settings/Constants/ColumnMap/ErrorColumnMap/ValueMap/Routing)를 읽어 보관한다.</summary>
    public class AppConfig
    {
        public Dictionary<string, string> Settings = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public Dictionary<string, string> Constants = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public List<MapRow> ColumnMap = new List<MapRow>();
        public List<MapRow> ErrorMap = new List<MapRow>();
        public Dictionary<string, string> ValueMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        public List<RouteRow> Routing = new List<RouteRow>();

        public string Setting(string key)
        {
            string v;
            return Settings.TryGetValue(key, out v) ? v : "";
        }

        public string Constant(string key)
        {
            string v;
            return Constants.TryGetValue(key, out v) ? v : "";
        }

        /// <summary>"Settings.ExcelCallSheet" 형태면 Settings 값으로 치환, 아니면 그대로 돌려준다.</summary>
        public string ResolveRef(string s)
        {
            if (s != null && s.StartsWith("Settings.", StringComparison.OrdinalIgnoreCase))
                return Setting(s.Substring("Settings.".Length));
            return s ?? "";
        }

        public static AppConfig Load(ExcelApp xl, string path, IDictionary<string, string> overrides)
        {
            var cfg = new AppConfig();
            object wb = xl.OpenWorkbook(path, true);
            try
            {
                foreach (var r in xl.ReadTable(xl.GetSheet(wb, "Settings")))
                {
                    string name = Get(r, "Name");
                    if (name.Length > 0) cfg.Settings[name] = Get(r, "Value");
                }
                foreach (var r in xl.ReadTable(xl.GetSheet(wb, "Constants")))
                {
                    string name = Get(r, "Name");
                    if (name.Length > 0) cfg.Constants[name] = Get(r, "Value");
                }
                cfg.ColumnMap = ReadMap(xl.ReadTable(xl.GetSheet(wb, "ColumnMap")));
                cfg.ErrorMap = ReadMap(xl.ReadTable(xl.GetSheet(wb, "ErrorColumnMap")));
                foreach (var r in xl.ReadTable(xl.GetSheet(wb, "ValueMap")))
                {
                    if (!string.Equals(Get(r, "Enabled"), "Y", StringComparison.OrdinalIgnoreCase)) continue;
                    cfg.ValueMap[Get(r, "Group") + "|" + Get(r, "Source")] = Get(r, "Target");
                }
                foreach (var r in xl.ReadTable(xl.GetSheet(wb, "Routing")))
                {
                    var rr = new RouteRow();
                    rr.Status = Get(r, "Status");
                    rr.TargetSheet = Get(r, "TargetSheet");
                    rr.TargetTable = Get(r, "TargetTable");
                    if (rr.Status.Length > 0) cfg.Routing.Add(rr);
                }
            }
            finally
            {
                xl.CloseWorkbook(wb, false);
            }
            if (overrides != null)
            {
                foreach (var kv in overrides) cfg.Settings[kv.Key] = kv.Value;
            }
            return cfg;
        }

        private static List<MapRow> ReadMap(List<Dictionary<string, string>> rows)
        {
            var list = new List<MapRow>();
            foreach (var r in rows)
            {
                var m = new MapRow();
                int order;
                m.Order = int.TryParse(Get(r, "Order"), out order) ? order : 0;
                m.ExcelColumn = Get(r, "ExcelColumn");
                m.JsonPath = Get(r, "JsonPath");
                string dt = Get(r, "DataType");
                m.DataType = dt.Length > 0 ? dt : "string";
                m.WriteByRobot = string.Equals(Get(r, "WriteByRobot"), "Y", StringComparison.OrdinalIgnoreCase);
                m.RequiredWhen = Get(r, "RequiredWhen");
                m.Transform = Get(r, "Transform");
                if (m.ExcelColumn.Length > 0) list.Add(m);
            }
            return list;
        }

        private static string Get(Dictionary<string, string> d, string key)
        {
            string v;
            return d.TryGetValue(key, out v) ? v.Trim() : "";
        }
    }
}
