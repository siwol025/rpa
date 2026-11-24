' Step5: 최종 결과 JSON 조립 + 상태 판정  (Python: run_dummy.process 의 조립 부분, call_schema.json v1.0)
' In : maskedJson(String) Step4 결과 {"transcript","pii"}, analysisJson(String) Step3 결과 {"result","error","retry_count"},
'      sttStage(String) 앞 단계 실패 위치("INPUT"/"STT"), sttError(String) 그 실패 사유(없으면 ""), fileName(String), seq(Int32) 순번, nowIso(String) "yyyy-MM-ddTHH:mm:ss+09:00",
'      promptVersion, sttEngine, genaiModel(String)
' Out: docJson(String) 최종 JSON, assembleError(String; 성공이면 "")
' 상태 판정: 유형 확신도 0.6 미만 또는 화자 구분 불확실(speaker_confidence=LOW)이면 NEEDS_REVIEW, 분석 실패/STT 실패면 FAILED, 그 외 SUCCESS
docJson = ""
assembleError = ""
Try
    Dim typeLabels As New System.Collections.Generic.Dictionary(Of String, String)
    typeLabels("INQUIRY") = "질의"
    typeLabels("COMPLAINT") = "불만"
    typeLabels("SUGGESTION") = "건의"
    typeLabels("TRAINING") = "교육 내용"
    typeLabels("OTHER") = "기타 문의"

    Dim nowDt As System.DateTime = System.DateTime.ParseExact(nowIso.Substring(0, 19), "yyyy-MM-dd'T'HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture)
    Dim callId As String = nowDt.ToString("yyyyMMdd_HHmmss", System.Globalization.CultureInfo.InvariantCulture) & "_" & seq.ToString("000", System.Globalization.CultureInfo.InvariantCulture)

    Dim nullTok As Newtonsoft.Json.Linq.JToken = Newtonsoft.Json.Linq.JValue.CreateNull()
    Dim doc As New Newtonsoft.Json.Linq.JObject()
    Dim src As New Newtonsoft.Json.Linq.JObject()
    src("file_name") = fileName
    src("file_path") = fileName
    src("duration_sec") = Newtonsoft.Json.Linq.JValue.CreateNull()
    src("received_at") = nowIso
    Dim proc As New Newtonsoft.Json.Linq.JObject()
    proc("stt_engine") = sttEngine
    proc("genai_model") = genaiModel
    proc("prompt_version") = promptVersion
    proc("retry_count") = 0
    proc("processed_at") = nowIso

    doc("schema_version") = "1.0"
    doc("call_id") = callId
    doc("source") = src
    doc("call_datetime") = Newtonsoft.Json.Linq.JValue.CreateNull()
    doc("agent_name") = Newtonsoft.Json.Linq.JValue.CreateNull()
    doc("customer_company") = Newtonsoft.Json.Linq.JValue.CreateNull()

    ' 실패 건에 채우는 빈 분석 필드
    Dim fillEmpty As System.Action = Sub()
                                         doc("type") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("type_label") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("type_confidence") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("customer_question") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("agent_action") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("summary") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("follow_up_required") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("follow_up") = Newtonsoft.Json.Linq.JValue.CreateNull()
                                         doc("keywords") = New Newtonsoft.Json.Linq.JArray()
                                         doc("entities") = New Newtonsoft.Json.Linq.JArray()
                                     End Sub

    If sttError <> "" Then
        ' STT 단계 실패: 전사·마스킹 없이 실패 건으로
        Dim errObj As New Newtonsoft.Json.Linq.JObject()
        errObj("stage") = If(sttStage = "", "STT", sttStage)
        errObj("reason") = sttError
        doc("status") = "FAILED"
        doc("error") = errObj
        fillEmpty()
        Dim emptyTr As New Newtonsoft.Json.Linq.JObject()
        emptyTr("full_text") = Newtonsoft.Json.Linq.JValue.CreateNull()
        emptyTr("segments") = New Newtonsoft.Json.Linq.JArray()
        emptyTr("speaker_confidence") = Newtonsoft.Json.Linq.JValue.CreateNull()
        Dim emptyPii As New Newtonsoft.Json.Linq.JObject()
        emptyPii("masked") = False
        emptyPii("counts") = New Newtonsoft.Json.Linq.JObject()
        doc("transcript") = emptyTr
        doc("pii") = emptyPii
    Else
        Dim rdM As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(maskedJson))
        rdM.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
        Dim maskedObj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rdM)
        Dim rdA As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(analysisJson))
        rdA.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
        Dim analysisObj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rdA)

        Dim trTok As Newtonsoft.Json.Linq.JObject = CType(maskedObj("transcript"), Newtonsoft.Json.Linq.JObject)
        Dim segArr As Newtonsoft.Json.Linq.JArray = CType(trTok("segments"), Newtonsoft.Json.Linq.JArray)
        src("duration_sec") = segArr(segArr.Count - 1)("end_sec").DeepClone()
        proc("retry_count") = analysisObj("retry_count").DeepClone()

        Dim speakerLow As Boolean = False
        Dim spTok As Newtonsoft.Json.Linq.JToken = trTok("speaker_confidence")
        If spTok IsNot Nothing AndAlso spTok.Type = Newtonsoft.Json.Linq.JTokenType.String Then speakerLow = (spTok.ToObject(Of String)() = "LOW")

        If analysisObj("error").Type <> Newtonsoft.Json.Linq.JTokenType.Null Then
            ' 분석(검증·재시도) 실패
            doc("status") = "FAILED"
            doc("error") = analysisObj("error").DeepClone()
            fillEmpty()
        Else
            Dim res As Newtonsoft.Json.Linq.JObject = CType(analysisObj("result"), Newtonsoft.Json.Linq.JObject)
            Dim lowConf As Boolean = (res("type_confidence").ToObject(Of Double)() < 0.6)
            doc("status") = If(lowConf OrElse speakerLow, "NEEDS_REVIEW", "SUCCESS")
            doc("error") = Newtonsoft.Json.Linq.JValue.CreateNull()
            For Each prop As Newtonsoft.Json.Linq.JProperty In res.Properties()
                doc(prop.Name) = prop.Value.DeepClone()
            Next
            doc("type_label") = typeLabels(res("type").ToObject(Of String)())
        End If
        doc("transcript") = trTok.DeepClone()
        doc("pii") = maskedObj("pii").DeepClone()
    End If
    doc("processing") = proc
    docJson = doc.ToString(Newtonsoft.Json.Formatting.None)
Catch ex As System.Exception
    assembleError = "결과 조립 실패(" & ex.GetType().Name & "): " & ex.Message
    docJson = ""
End Try
