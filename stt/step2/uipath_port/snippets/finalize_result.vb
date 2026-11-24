' Step3: 재시도 결과 정리  (Python: analyze.analyze 의 반환값 — (result, error, retry_count))
' In : isDone(Boolean) 성공 여부, cleanedJson(String) 성공한 시도의 검증된 JSON, lastError(String) 마지막 실패 사유,
'      maxRetry(Int32) 최대 재시도 횟수, attemptUsed(Int32) 성공한 시도 번호(0부터)
' Out: finalJson(String) {"result": {...}|null, "error": {"stage","reason"}|null, "retry_count": n}
Dim finalObj As New Newtonsoft.Json.Linq.JObject()
If isDone Then
    Dim rd As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(cleanedJson))
    rd.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    finalObj("result") = Newtonsoft.Json.Linq.JObject.Load(rd)
    finalObj("error") = Newtonsoft.Json.Linq.JValue.CreateNull()
    finalObj("retry_count") = attemptUsed
Else
    Dim errObj As New Newtonsoft.Json.Linq.JObject()
    errObj("stage") = "VALIDATION"
    errObj("reason") = "재시도 " & maxRetry.ToString() & "회 후에도 실패: " & lastError
    finalObj("result") = Newtonsoft.Json.Linq.JValue.CreateNull()
    finalObj("error") = errObj
    finalObj("retry_count") = maxRetry
End If
finalJson = finalObj.ToString(Newtonsoft.Json.Formatting.None)
