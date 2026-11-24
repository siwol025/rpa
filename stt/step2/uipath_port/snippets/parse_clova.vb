' Step7: STT 응답 파싱·화자 매핑  (Python: parse_clova.to_transcript)
' In : sttJson(String) CLOVA Speech 응답 원본 JSON
' Out: transcriptJson(String) {"full_text","segments":[{"speaker","start_sec","end_sec","text"}],"speaker_confidence"},
'      parseError(String; 성공이면 ""), resultJson(String; {"transcript": 객체|null, "error": "…"} — 테스트 비교용)
transcriptJson = ""
resultJson = ""
parseError = ""
Try
    Dim rd As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(sttJson))
    rd.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    Dim resp As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rd)

    ' Python 의 str() 처럼 값을 문자열로
    Dim pyStr As System.Func(Of Newtonsoft.Json.Linq.JToken, String) = Function(t As Newtonsoft.Json.Linq.JToken) As String
                                                                           Dim r As String
                                                                           If t Is Nothing OrElse t.Type = Newtonsoft.Json.Linq.JTokenType.Null Then
                                                                               r = "None"
                                                                           ElseIf t.Type = Newtonsoft.Json.Linq.JTokenType.String Then
                                                                               r = CStr(CType(t, Newtonsoft.Json.Linq.JValue).Value)
                                                                           ElseIf t.Type = Newtonsoft.Json.Linq.JTokenType.Boolean Then
                                                                               r = If(CBool(CType(t, Newtonsoft.Json.Linq.JValue).Value), "True", "False")
                                                                           ElseIf t.Type = Newtonsoft.Json.Linq.JTokenType.Integer Then
                                                                               r = System.Convert.ToString(CType(t, Newtonsoft.Json.Linq.JValue).Value, System.Globalization.CultureInfo.InvariantCulture)
                                                                           ElseIf t.Type = Newtonsoft.Json.Linq.JTokenType.Float Then
                                                                               Dim dv As Double = CDbl(CType(t, Newtonsoft.Json.Linq.JValue).Value)
                                                                               r = dv.ToString("R", System.Globalization.CultureInfo.InvariantCulture)
                                                                               If dv = System.Math.Floor(dv) AndAlso Not r.Contains("E") Then r = r & ".0"
                                                                           Else
                                                                               r = t.ToString(Newtonsoft.Json.Formatting.None)
                                                                           End If
                                                                           Return r
                                                                       End Function

    ' round(ms / 1000.0, 2) — Python 과 똑같이(이진 부동소수점의 정확한 값 기준, 동률은 짝수로) 반올림. 정수 연산만 사용.
    Dim roundSec As System.Func(Of Double, Double) = Function(msv As Double) As Double
                                                         Dim d As Double = msv / 1000.0
                                                         Dim neg As Boolean = (d < 0)
                                                         If neg Then d = -d
                                                         Dim bits As Long = System.BitConverter.DoubleToInt64Bits(d)
                                                         Dim expBits As Integer = CInt((bits >> 52) And &H7FFL)
                                                         Dim frac As ULong = CULng(bits And &HFFFFFFFFFFFFFL)
                                                         Dim q As ULong = 0UL
                                                         If expBits <> 0 Then
                                                             Dim mant As ULong = frac Or (1UL << 52)
                                                             Dim e2 As Integer = expBits - 1075
                                                             If e2 >= 0 Then
                                                                 q = CULng(d * 100.0)
                                                             Else
                                                                 Dim sh As Integer = -e2
                                                                 If sh < 64 Then
                                                                     Dim n As ULong = mant * 100UL
                                                                     Dim one As ULong = 1UL << sh
                                                                     q = n >> sh
                                                                     Dim rem2 As ULong = n And (one - 1UL)
                                                                     Dim half As ULong = one >> 1
                                                                     If rem2 > half Then
                                                                         q = q + 1UL
                                                                     ElseIf rem2 = half Then
                                                                         If (q And 1UL) = 1UL Then q = q + 1UL
                                                                     End If
                                                                 End If
                                                             End If
                                                         End If
                                                         Dim res As Double = CDbl(q) / 100.0
                                                         If neg Then res = -res
                                                         Return res
                                                     End Function

    ' 1) 응답 확인 (Python: extract_segments)
    Dim resultTok As Newtonsoft.Json.Linq.JToken = resp("result")
    If resultTok Is Nothing OrElse resultTok.Type <> Newtonsoft.Json.Linq.JTokenType.String OrElse CStr(CType(resultTok, Newtonsoft.Json.Linq.JValue).Value) <> "COMPLETED" Then
        parseError = "COMPLETED 상태가 아닌 응답: " & pyStr(resultTok)
    Else
        Dim labels As New System.Collections.Generic.List(Of String)
        Dim starts As New System.Collections.Generic.List(Of Double)
        Dim ends As New System.Collections.Generic.List(Of Double)
        Dim texts As New System.Collections.Generic.List(Of String)
        Dim segTok As Newtonsoft.Json.Linq.JToken = resp("segments")
        If segTok IsNot Nothing AndAlso segTok.Type = Newtonsoft.Json.Linq.JTokenType.Array Then
            For Each s As Newtonsoft.Json.Linq.JToken In segTok.Children()
                Dim so As Newtonsoft.Json.Linq.JObject = TryCast(s, Newtonsoft.Json.Linq.JObject)
                If so Is Nothing Then Throw New System.InvalidOperationException("segments 항목이 객체가 아님")
                Dim tEdit As Newtonsoft.Json.Linq.JToken = so("textEdited")
                Dim tText As Newtonsoft.Json.Linq.JToken = so("text")
                Dim txt As String = ""
                If tEdit IsNot Nothing AndAlso tEdit.Type = Newtonsoft.Json.Linq.JTokenType.String AndAlso CStr(CType(tEdit, Newtonsoft.Json.Linq.JValue).Value).Length > 0 Then
                    txt = CStr(CType(tEdit, Newtonsoft.Json.Linq.JValue).Value)
                ElseIf tText IsNot Nothing AndAlso tText.Type = Newtonsoft.Json.Linq.JTokenType.String Then
                    txt = CStr(CType(tText, Newtonsoft.Json.Linq.JValue).Value)
                End If
                txt = txt.Trim()
                If txt.Length > 0 Then
                    ' 화자 라벨: speaker.label → diarization.label → "?"
                    Dim lbl As String = "?"
                    Dim spObj As Newtonsoft.Json.Linq.JObject = TryCast(so("speaker"), Newtonsoft.Json.Linq.JObject)
                    Dim dzObj As Newtonsoft.Json.Linq.JObject = TryCast(so("diarization"), Newtonsoft.Json.Linq.JObject)
                    Dim spLabel As Newtonsoft.Json.Linq.JToken = Nothing
                    Dim dzLabel As Newtonsoft.Json.Linq.JToken = Nothing
                    If spObj IsNot Nothing Then spLabel = spObj("label")
                    If dzObj IsNot Nothing Then dzLabel = dzObj("label")
                    If spLabel IsNot Nothing AndAlso spLabel.Type <> Newtonsoft.Json.Linq.JTokenType.Null AndAlso Not (spLabel.Type = Newtonsoft.Json.Linq.JTokenType.String AndAlso CStr(CType(spLabel, Newtonsoft.Json.Linq.JValue).Value) = "") Then
                        lbl = pyStr(spLabel)
                    ElseIf dzLabel IsNot Nothing AndAlso dzLabel.Type <> Newtonsoft.Json.Linq.JTokenType.Null AndAlso Not (dzLabel.Type = Newtonsoft.Json.Linq.JTokenType.String AndAlso CStr(CType(dzLabel, Newtonsoft.Json.Linq.JValue).Value) = "") Then
                        lbl = pyStr(dzLabel)
                    End If
                    ' 시작·끝 (ms → 초, 소수 2자리). 없으면 0
                    Dim ms2 As Double() = New Double() {0.0, 0.0}
                    Dim keys2 As String() = New String() {"start", "end"}
                    For k As Integer = 0 To 1
                        Dim vt As Newtonsoft.Json.Linq.JToken = so(keys2(k))
                        If vt IsNot Nothing Then
                            If vt.Type = Newtonsoft.Json.Linq.JTokenType.Integer OrElse vt.Type = Newtonsoft.Json.Linq.JTokenType.Float Then
                                ms2(k) = CDbl(CType(vt, Newtonsoft.Json.Linq.JValue).Value)
                            ElseIf vt.Type = Newtonsoft.Json.Linq.JTokenType.String Then
                                Dim parsed As Double
                                If Not System.Double.TryParse(CStr(CType(vt, Newtonsoft.Json.Linq.JValue).Value), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, parsed) Then
                                    Throw New System.FormatException("could not convert string to float: '" & CStr(CType(vt, Newtonsoft.Json.Linq.JValue).Value) & "'")
                                End If
                                ms2(k) = parsed
                            Else
                                Throw New System.FormatException("float() argument must be a string or a real number, not '" & If(vt.Type = Newtonsoft.Json.Linq.JTokenType.Null, "NoneType", vt.Type.ToString()) & "'")
                            End If
                        End If
                    Next
                    labels.Add(lbl)
                    starts.Add(roundSec(ms2(0)))
                    ends.Add(roundSec(ms2(1)))
                    texts.Add(txt)
                End If
            Next
        End If
        If texts.Count = 0 Then
            parseError = "발화가 없음"
        Else
            ' 2) 같은 화자의 연속 발화 병합 (Python: merge_consecutive)
            Dim mLabels As New System.Collections.Generic.List(Of String)
            Dim mStarts As New System.Collections.Generic.List(Of Double)
            Dim mEnds As New System.Collections.Generic.List(Of Double)
            Dim mTexts As New System.Collections.Generic.List(Of String)
            For i As Integer = 0 To texts.Count - 1
                If mLabels.Count > 0 AndAlso mLabels(mLabels.Count - 1) = labels(i) Then
                    mTexts(mTexts.Count - 1) = mTexts(mTexts.Count - 1) & " " & texts(i)
                    mEnds(mEnds.Count - 1) = ends(i)
                Else
                    mLabels.Add(labels(i))
                    mStarts.Add(starts(i))
                    mEnds.Add(ends(i))
                    mTexts.Add(texts(i))
                End If
            Next

            ' 3) 화자 라벨 → 상담원/고객 (Python: assign_roles)
            Dim greetingKeywords As String() = New String() {"고객지원센터", "고객센터", "상담원", "무엇을 도와"}
            Dim agentPhrases As String() = New String() {"고객지원센터", "고객센터입니다", "무엇을 도와", "도와드리", "도와 드리", "안내해 드리", "안내드리", "확인해 보겠", "확인해보겠", "죄송합니다", "보내 드리겠", "말씀해 주", "확인 후"}
            Dim uniq As New System.Collections.Generic.List(Of String)
            For Each lb As String In mLabels
                If Not uniq.Contains(lb) Then uniq.Add(lb)
            Next
            Dim score As New System.Collections.Generic.Dictionary(Of String, Integer)
            Dim firstUtt As New System.Collections.Generic.Dictionary(Of String, String)
            For Each lb As String In uniq
                score(lb) = 0
            Next
            For i As Integer = 0 To mTexts.Count - 1
                If Not firstUtt.ContainsKey(mLabels(i)) Then firstUtt(mLabels(i)) = mTexts(i)
                For Each ph As String In agentPhrases
                    Dim pos As Integer = mTexts(i).IndexOf(ph, System.StringComparison.Ordinal)
                    Do While pos >= 0
                        score(mLabels(i)) = score(mLabels(i)) + 1
                        pos = mTexts(i).IndexOf(ph, pos + ph.Length, System.StringComparison.Ordinal)
                    Loop
                Next
            Next
            Dim roles As New System.Collections.Generic.Dictionary(Of String, String)
            Dim conf As String
            If uniq.Count < 2 Then
                roles(uniq(0)) = "UNKNOWN"
                conf = "LOW"
            Else
                Dim firstL As String = uniq(0)
                Dim secondL As String = uniq(1)
                Dim greeters As New System.Collections.Generic.List(Of String)
                For Each lb As String In uniq
                    Dim isG As Boolean = False
                    For Each kw As String In greetingKeywords
                        If firstUtt(lb).Contains(kw) Then isG = True
                    Next
                    If isG Then greeters.Add(lb)
                Next
                If greeters.Count = 1 AndAlso uniq.Count = 2 Then
                    Dim ag As String = greeters(0)
                    Dim cu As String = If(ag = firstL, secondL, firstL)
                    roles(ag) = "AGENT"
                    roles(cu) = "CUSTOMER"
                    conf = "HIGH"
                Else
                    Dim a As Integer = score(firstL)
                    Dim b As Integer = score(secondL)
                    Dim agent As String
                    If System.Math.Abs(a - b) >= 2 Then
                        agent = If(a > b, firstL, secondL)
                        conf = If(agent = firstL, "HIGH", "LOW")
                    Else
                        agent = firstL
                        conf = If(a > b, "HIGH", "LOW")
                    End If
                    Dim customer As String = If(agent = firstL, secondL, firstL)
                    roles(agent) = "AGENT"
                    roles(customer) = "CUSTOMER"
                    For i As Integer = 2 To uniq.Count - 1
                        roles(uniq(i)) = "UNKNOWN"
                        conf = "LOW"
                    Next
                End If
            End If

            ' 4) 전사 객체와 '[상담원] … / [고객] …' 형식 전문
            Dim roleLabel As New System.Collections.Generic.Dictionary(Of String, String)
            roleLabel("AGENT") = "상담원"
            roleLabel("CUSTOMER") = "고객"
            roleLabel("UNKNOWN") = "알수없음"
            Dim segsOut As New Newtonsoft.Json.Linq.JArray()
            Dim lines As New System.Collections.Generic.List(Of String)
            For i As Integer = 0 To mTexts.Count - 1
                Dim o As New Newtonsoft.Json.Linq.JObject()
                o("speaker") = roles(mLabels(i))
                o("start_sec") = mStarts(i)
                o("end_sec") = mEnds(i)
                o("text") = mTexts(i)
                segsOut.Add(o)
                lines.Add("[" & roleLabel(roles(mLabels(i))) & "] " & mTexts(i))
            Next
            Dim trOut As New Newtonsoft.Json.Linq.JObject()
            trOut("full_text") = String.Join(vbLf, lines)
            trOut("segments") = segsOut
            trOut("speaker_confidence") = conf
            transcriptJson = trOut.ToString(Newtonsoft.Json.Formatting.None)
        End If
    End If
Catch ex As System.Exception
    transcriptJson = ""
    If TypeOf ex Is Newtonsoft.Json.JsonException Then
        parseError = "응답 JSON을 읽을 수 없음(JSONDecodeError)"
    Else
        parseError = ex.Message
    End If
End Try

Dim resultObj As New Newtonsoft.Json.Linq.JObject()
If transcriptJson <> "" Then
    Dim rdT As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(transcriptJson))
    rdT.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    resultObj("transcript") = Newtonsoft.Json.Linq.JObject.Load(rdT)
Else
    resultObj("transcript") = Newtonsoft.Json.Linq.JValue.CreateNull()
End If
resultObj("error") = parseError
resultJson = resultObj.ToString(Newtonsoft.Json.Formatting.None)
