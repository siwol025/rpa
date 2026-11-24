' Step8: 최종 JSON 에서 로그·분기에 쓸 값을 꺼낸다 (결과 문서의 status / error / processing.retry_count)
' In : docJson(String) Step5 가 만든 최종 JSON
' Out: docStatus(String) SUCCESS/NEEDS_REVIEW/FAILED (읽지 못하면 "UNKNOWN"), errStage(String), errReason(String) (오류가 없으면 ""), retryCount(Int32)
docStatus = ""
errStage = ""
errReason = ""
retryCount = 0
Try
    Dim rdDoc As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(docJson))
    rdDoc.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    Dim docObj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rdDoc)
    docStatus = docObj.Value(Of String)("status")
    Dim errTok As Newtonsoft.Json.Linq.JToken = docObj("error")
    If errTok IsNot Nothing AndAlso errTok.Type = Newtonsoft.Json.Linq.JTokenType.Object Then
        errStage = CType(errTok, Newtonsoft.Json.Linq.JObject).Value(Of String)("stage")
        errReason = CType(errTok, Newtonsoft.Json.Linq.JObject).Value(Of String)("reason")
    End If
    retryCount = CType(docObj("processing"), Newtonsoft.Json.Linq.JObject).Value(Of Integer)("retry_count")
Catch ex As System.Exception
    docStatus = "UNKNOWN"
End Try
