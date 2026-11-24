' Step2: 응답 JSON 추출·검증  (Python: analyze.extract_json + analyze.validate + 필드 화이트리스트)
' In : responseText(String) 모델이 돌려준 원문
' Out: isValid(Boolean), errorText(String; 성공이면 ""), cleanedJson(String; 성공 시 정의된 필드만 남긴 JSON),
'      resultJson(String; {"isValid","errorText","cleaned"} — 테스트 비교용)
isValid = False
errorText = ""
cleanedJson = ""
resultJson = ""
Dim parseLabel As String = ""
Dim root As Newtonsoft.Json.Linq.JObject = Nothing
Dim cleaned As Newtonsoft.Json.Linq.JObject = Nothing
Dim errs As New System.Collections.Generic.List(Of String)

' 1) 코드펜스 제거 후 첫 '{' ~ 마지막 '}' 구간을 JSON으로 파싱 (Python: extract_json)
Dim txt As String = System.Text.RegularExpressions.Regex.Replace(If(responseText, ""), "```(?:json)?", "").Trim()
Dim sIdx As Integer = txt.IndexOf("{", System.StringComparison.Ordinal)
Dim eIdx As Integer = txt.LastIndexOf("}", System.StringComparison.Ordinal)
If sIdx < 0 OrElse eIdx <= sIdx Then
    parseLabel = "ValueError"
Else
    Try
        Dim rd As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(txt.Substring(sIdx, eIdx - sIdx + 1)))
        rd.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
        root = Newtonsoft.Json.Linq.JObject.Load(rd)
        If rd.Read() Then parseLabel = "JSONDecodeError"
    Catch ex As System.Exception
        parseLabel = "JSONDecodeError"
    End Try
End If

If parseLabel <> "" Then
    errorText = "응답 파싱 실패(" & parseLabel & ")"
Else
    Dim requiredKeys As String() = New String() {"type", "type_confidence", "customer_company", "customer_question", "agent_action", "summary", "follow_up_required", "follow_up", "keywords", "entities"}
    Dim typeCodes As New System.Collections.Generic.HashSet(Of String)(New String() {"INQUIRY", "COMPLAINT", "SUGGESTION", "TRAINING", "OTHER"})
    Dim entityTypes As New System.Collections.Generic.HashSet(Of String)(New String() {"PRODUCT", "ORG", "DATE", "AMOUNT", "REF_NO", "OTHER"})

    ' Python 의 repr 처럼 값을 표시 (오류 메시지 호환용)
    Dim pyRepr As System.Func(Of Newtonsoft.Json.Linq.JToken, String) = Function(t As Newtonsoft.Json.Linq.JToken) As String
                                                                             Dim r As String
                                                                             Select Case t.Type
                                                                                 Case Newtonsoft.Json.Linq.JTokenType.Null
                                                                                     r = "None"
                                                                                 Case Newtonsoft.Json.Linq.JTokenType.String
                                                                                     Dim sv As String = CStr(CType(t, Newtonsoft.Json.Linq.JValue).Value)
                                                                                     If sv.Contains("'") AndAlso Not sv.Contains("""") Then
                                                                                         r = """" & sv & """"
                                                                                     Else
                                                                                         r = "'" & sv.Replace("\", "\\").Replace("'", "\'").Replace(vbLf, "\n").Replace(vbCr, "\r").Replace(vbTab, "\t") & "'"
                                                                                     End If
                                                                                 Case Newtonsoft.Json.Linq.JTokenType.Boolean
                                                                                     r = If(CBool(CType(t, Newtonsoft.Json.Linq.JValue).Value), "True", "False")
                                                                                 Case Newtonsoft.Json.Linq.JTokenType.Integer
                                                                                     r = System.Convert.ToString(CType(t, Newtonsoft.Json.Linq.JValue).Value, System.Globalization.CultureInfo.InvariantCulture)
                                                                                 Case Newtonsoft.Json.Linq.JTokenType.Float
                                                                                     Dim dv As Double = CDbl(CType(t, Newtonsoft.Json.Linq.JValue).Value)
                                                                                     r = dv.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                                                                                     If dv = System.Math.Floor(dv) AndAlso Not r.Contains("E") Then r = r & ".0"
                                                                                 Case Else
                                                                                     r = t.ToString(Newtonsoft.Json.Formatting.None)
                                                                             End Select
                                                                             Return r
                                                                         End Function
    ' Python 의 truthiness (not x.get("value") 판정용)
    Dim truthy As System.Func(Of Newtonsoft.Json.Linq.JToken, Boolean) = Function(t As Newtonsoft.Json.Linq.JToken) As Boolean
                                                                              Dim r As Boolean = False
                                                                              If t IsNot Nothing Then
                                                                                  Select Case t.Type
                                                                                      Case Newtonsoft.Json.Linq.JTokenType.Null
                                                                                          r = False
                                                                                      Case Newtonsoft.Json.Linq.JTokenType.String
                                                                                          r = CStr(CType(t, Newtonsoft.Json.Linq.JValue).Value).Length > 0
                                                                                      Case Newtonsoft.Json.Linq.JTokenType.Boolean
                                                                                          r = CBool(CType(t, Newtonsoft.Json.Linq.JValue).Value)
                                                                                      Case Newtonsoft.Json.Linq.JTokenType.Integer, Newtonsoft.Json.Linq.JTokenType.Float
                                                                                          r = CDbl(CType(t, Newtonsoft.Json.Linq.JValue).Value) <> 0
                                                                                      Case Newtonsoft.Json.Linq.JTokenType.Array, Newtonsoft.Json.Linq.JTokenType.Object
                                                                                          r = t.HasValues
                                                                                      Case Else
                                                                                          r = True
                                                                                  End Select
                                                                              End If
                                                                              Return r
                                                                          End Function

    ' 2) 필수 키 (하나라도 없으면 거기서 끝, Python: errs 가 있으면 즉시 반환)
    For Each k As String In requiredKeys
        If root(k) Is Nothing Then errs.Add(k & " 누락")
    Next

    ' 3) 값 검증 (Python: validate)
    If errs.Count = 0 Then
        Dim typeTok As Newtonsoft.Json.Linq.JToken = root("type")
        If Not (typeTok.Type = Newtonsoft.Json.Linq.JTokenType.String AndAlso typeCodes.Contains(CStr(CType(typeTok, Newtonsoft.Json.Linq.JValue).Value))) Then
            errs.Add("type enum 위반: " & pyRepr(typeTok))
        End If

        Dim confTok As Newtonsoft.Json.Linq.JToken = root("type_confidence")
        Dim confOk As Boolean = False
        If confTok.Type = Newtonsoft.Json.Linq.JTokenType.Integer OrElse confTok.Type = Newtonsoft.Json.Linq.JTokenType.Float Then
            Dim cv As Double = CDbl(CType(confTok, Newtonsoft.Json.Linq.JValue).Value)
            confOk = (cv >= 0.0 AndAlso cv <= 1.0)
        End If
        If Not confOk Then errs.Add("type_confidence 범위 위반")

        Dim sumTok As Newtonsoft.Json.Linq.JToken = root("summary")
        Dim sumOk As Boolean = False
        If sumTok.Type = Newtonsoft.Json.Linq.JTokenType.String Then
            Dim sl As Integer = CStr(CType(sumTok, Newtonsoft.Json.Linq.JValue).Value).Length
            sumOk = (sl > 0 AndAlso sl <= 300)
        End If
        If Not sumOk Then errs.Add("summary 비었거나 300자 초과")

        For Each k As String In New String() {"customer_question", "agent_action"}
            Dim tk As Newtonsoft.Json.Linq.JToken = root(k)
            If tk.Type <> Newtonsoft.Json.Linq.JTokenType.Null Then
                Dim okLen As Boolean = False
                If tk.Type = Newtonsoft.Json.Linq.JTokenType.String Then
                    Dim ln As Integer = CStr(CType(tk, Newtonsoft.Json.Linq.JValue).Value).Length
                    okLen = (ln > 0 AndAlso ln <= 200)
                End If
                If Not okLen Then errs.Add(k & " 길이/형식 위반")
            End If
        Next

        If root("follow_up_required").Type <> Newtonsoft.Json.Linq.JTokenType.Boolean Then errs.Add("follow_up_required는 boolean")

        Dim kwTok As Newtonsoft.Json.Linq.JToken = root("keywords")
        If Not (kwTok.Type = Newtonsoft.Json.Linq.JTokenType.Array AndAlso CType(kwTok, Newtonsoft.Json.Linq.JArray).Count <= 5) Then errs.Add("keywords는 최대 5개 배열")

        Dim entTok As Newtonsoft.Json.Linq.JToken = root("entities")
        Dim entOk As Boolean = (entTok.Type = Newtonsoft.Json.Linq.JTokenType.Array)
        If entOk Then
            For Each item As Newtonsoft.Json.Linq.JToken In entTok.Children()
                If item.Type <> Newtonsoft.Json.Linq.JTokenType.Object Then
                    entOk = False
                Else
                    Dim itemType As Newtonsoft.Json.Linq.JToken = CType(item, Newtonsoft.Json.Linq.JObject)("type")
                    Dim itemValue As Newtonsoft.Json.Linq.JToken = CType(item, Newtonsoft.Json.Linq.JObject)("value")
                    If Not (itemType IsNot Nothing AndAlso itemType.Type = Newtonsoft.Json.Linq.JTokenType.String AndAlso entityTypes.Contains(CStr(CType(itemType, Newtonsoft.Json.Linq.JValue).Value)) AndAlso truthy(itemValue)) Then entOk = False
                End If
            Next
        End If
        If Not entOk Then errs.Add("entities 형식 위반")
    End If

    ' 4) 결과: 정의된 필드만 남긴다 (정의되지 않은 필드는 결과에 싣지 않음)
    If errs.Count > 0 Then
        errorText = String.Join("; ", errs)
    Else
        cleaned = New Newtonsoft.Json.Linq.JObject()
        For Each k As String In requiredKeys
            cleaned.Add(k, root(k).DeepClone())
        Next
        cleanedJson = cleaned.ToString(Newtonsoft.Json.Formatting.None)
        isValid = True
    End If
End If

Dim outObj As New Newtonsoft.Json.Linq.JObject()
outObj("isValid") = isValid
outObj("errorText") = errorText
If isValid Then outObj("cleaned") = cleaned Else outObj("cleaned") = Newtonsoft.Json.Linq.JValue.CreateNull()
resultJson = outObj.ToString(Newtonsoft.Json.Formatting.None)
