using System;
using System.Text.Json;

namespace CallCenter
{
    /// <summary>업무 규칙 위반(필수값 누락, 스키마 불일치 등). 재시도 없이 error 폴더로 보낸다.</summary>
    public class BusinessException : Exception
    {
        public BusinessException(string message) : base(message) { }
    }

    /// <summary>③이 만든 결과 JSON 한 건. "source.file_name" 같은 점 경로로 값을 꺼낸다.</summary>
    public class ResultJson : IDisposable
    {
        private readonly JsonDocument _doc;

        private ResultJson(JsonDocument doc) { _doc = doc; }

        public static ResultJson Parse(string text)
        {
            try
            {
                return new ResultJson(JsonDocument.Parse(text));
            }
            catch (JsonException ex)
            {
                throw new BusinessException("JSON 형식 오류: " + ex.Message);
            }
        }

        /// <summary>경로의 값을 문자열로 반환. 없거나 null이면 null. 불린은 "true"/"false".</summary>
        public string Get(string path)
        {
            if (string.IsNullOrWhiteSpace(path)) return null;
            JsonElement cur = _doc.RootElement;
            foreach (string part in path.Split('.'))
            {
                if (cur.ValueKind != JsonValueKind.Object) return null;
                JsonElement next;
                if (!cur.TryGetProperty(part, out next)) return null;
                cur = next;
            }
            switch (cur.ValueKind)
            {
                case JsonValueKind.Null:
                case JsonValueKind.Undefined:
                    return null;
                case JsonValueKind.String:
                    return cur.GetString();
                case JsonValueKind.True:
                    return "true";
                case JsonValueKind.False:
                    return "false";
                default:
                    return cur.GetRawText();
            }
        }

        public void Dispose() { _doc.Dispose(); }
    }
}
