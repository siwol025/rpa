' Step4: 개인정보(PII) 마스킹  (Python: mask_pii.mask_transcript / mask_text)
' In : transcriptJson(String) {"full_text","segments":[{"speaker","start_sec","end_sec","text"}],"speaker_confidence"}  (parse_clova 결과)
' Out: maskedJson(String) {"transcript": 마스킹된 전사, "pii": {"masked": true, "counts": {...}}},
'      maskedFullText(String) 마스킹된 전문("[상담원] ...\n[고객] ..."), maskError(String; 성공이면 "")
maskedJson = ""
maskedFullText = ""
maskError = ""
Dim counts As New System.Collections.Generic.Dictionary(Of String, Integer)
For Each ck As String In New String() {"phone", "rrn", "card", "account", "email", "name", "address", "password", "birth", "id"}
    counts(ck) = 0
Next

' 적용 순서가 중요하다 (긴/구체적인 패턴 먼저). Python 의 RULES 와 같은 순서·같은 패턴.
Dim prov As String = "(?:서울특별시|서울시|서울|부산광역시|부산|대구광역시|대구|인천광역시|인천|광주광역시|광주|대전광역시|대전|" & _
    "울산광역시|울산|세종특별자치시|세종|경기도|경기|강원특별자치도|강원도|강원|충청북도|충북|충청남도|충남|" & _
    "전북특별자치도|전라북도|전북|전라남도|전남|경상북도|경북|경상남도|경남|제주특별자치도|제주도|제주)"
Dim kinds As String() = New String() {"email", "address", "address", "rrn", "card", "phone", "email", "account", "birth"}
Dim tokens As String() = New String() {"[EMAIL]", "[ADDRESS]", "[ADDRESS]", "[RRN]", "[CARD]", "[PHONE]", "[EMAIL]", "[ACCOUNT]", "[BIRTH]"}
Dim patterns As String() = New String() { _
    "[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,3}\s*골뱅이\s*[가-힣A-Za-z0-9]+(?:\s*점\s*(?:컴|닷컴|넷|케이알|씨오|com|net|kr|co)){1,2}", _
    "[가-힣]{1,6}[동읍면리]\s+[가-힣0-9]+(?:\s*\d+\s*(?:차|단지|동|호))*\s*(?:아파트|빌라|오피스텔|APT)", _
    prov & "\s*[가-힣]{1,6}[시군구]\s+(?:[가-힣0-9\-]+\s+){0,5}[가-힣0-9\-]*\d[가-힣0-9\-]*", _
    "(?<!\d)\d{6}\s*[-–]\s*[1-4]\d{6}(?!\d)", _
    "(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)", _
    "(?<!\d)(?:01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4})(?!\d)", _
    "[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", _
    "(?<!\d)\d{2,6}-\d{2,6}-\d{4,8}(?:-\d{1,3})?(?!\d)", _
    "(?<!\d)(?:19|20)?\d{2}년생"}
' 비밀번호: 앞 문맥('비밀번호는')은 남기고 값 어절들만 치환
Dim pwTok As String = "(?:[A-Za-z0-9]+|느낌표|골뱅이|별표|샵|언더바|물결|대시|하이픈)[가-힣]{0,2}"
Dim passwordPattern As String = "(비밀\s?번호(?:는|가|를|도)?\s*)(" & pwTok & "(?:\s+" & pwTok & ")*)"
' 카드번호를 말로 불러 준 경우: "카드번호는 02345-5648632 다시 132546974이고요" (그룹 1 문맥은 유지)
Dim cardSpokenPattern As String = "(카드\s?번호(?:는|가|를|도)?\s*)((?:\d[\d\-]*(?:\s*다시\s*)?)+)"
' 비밀번호 앞·뒷자리: "비밀번호 앞자리는 00이에요"
Dim passwordPartPattern As String = "(비밀\s?번호\s*(?:앞|뒷|뒤)\s?자리(?:는|가|를|도)?\s*)(\d{1,6})"
' 아이디: "아이디는 dabin jang으로" (영문·숫자 어절만)
Dim idPattern As String = "(아이디(?:는|가|를|도)?\s*)([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+){0,2})(?=[가-힣\s,.]|$)"
' 이름: 그룹 1(앞 문맥)은 남기고 그룹 2(이름)만 치환
Dim namePatterns As String() = New String() { _
    "(상담원\s*)([가-힣]{2,4})(?=\s*(?:입니다|이에요|예요|이라고))", _
    "((?:제\s*이름은|성함은|이름은|저는)\s*)([가-힣]{2,4})(?=\s*(?:입니다|이에요|예요|이라고|씨|님|인데))", _
    "((?:아이\s*|자녀\s*|아들\s*|딸\s*)?이름은\s*)([가-힣]{2,4})(?=\s*(?:이고|이며|이구요|이에요|예요|입니다))", _
    "((?:^|[.?!]\s+))([가-힣]{3})(?=이었습니다)"}
Dim nameStopWords As New System.Collections.Generic.HashSet(Of String)(New String() {"고객", "상담원", "담당자", "회원", "관리자", "그것", "이것", "문제", "원인", "결과", "내용"})

Dim pwEval As System.Text.RegularExpressions.MatchEvaluator = Function(m As System.Text.RegularExpressions.Match) As String
                                                                  Return m.Groups(1).Value & "[PASSWORD]"
                                                              End Function
Dim cardEval As System.Text.RegularExpressions.MatchEvaluator = Function(m As System.Text.RegularExpressions.Match) As String
                                                                    Return m.Groups(1).Value & "[CARD]"
                                                                End Function
Dim idEval As System.Text.RegularExpressions.MatchEvaluator = Function(m As System.Text.RegularExpressions.Match) As String
                                                                  Return m.Groups(1).Value & "[ID]"
                                                              End Function
Dim nameEval As System.Text.RegularExpressions.MatchEvaluator = Function(m As System.Text.RegularExpressions.Match) As String
                                                                    Dim nm As String
                                                                    If nameStopWords.Contains(m.Groups(2).Value) Then
                                                                        nm = m.Value
                                                                    Else
                                                                        counts("name") = counts("name") + 1
                                                                        nm = m.Groups(1).Value & "[NAME]"
                                                                    End If
                                                                    Return nm
                                                                End Function
Dim maskText As System.Func(Of String, String) = Function(t As String) As String
                                                     Dim cur As String = t
                                                     For i As Integer = 0 To kinds.Length - 1
                                                         counts(kinds(i)) = counts(kinds(i)) + System.Text.RegularExpressions.Regex.Matches(cur, patterns(i)).Count
                                                         cur = System.Text.RegularExpressions.Regex.Replace(cur, patterns(i), tokens(i))
                                                     Next
                                                     counts("card") = counts("card") + System.Text.RegularExpressions.Regex.Matches(cur, cardSpokenPattern).Count
                                                     cur = System.Text.RegularExpressions.Regex.Replace(cur, cardSpokenPattern, cardEval)
                                                     counts("password") = counts("password") + System.Text.RegularExpressions.Regex.Matches(cur, passwordPartPattern).Count
                                                     cur = System.Text.RegularExpressions.Regex.Replace(cur, passwordPartPattern, pwEval)
                                                     counts("password") = counts("password") + System.Text.RegularExpressions.Regex.Matches(cur, passwordPattern).Count
                                                     cur = System.Text.RegularExpressions.Regex.Replace(cur, passwordPattern, pwEval)
                                                     counts("id") = counts("id") + System.Text.RegularExpressions.Regex.Matches(cur, idPattern).Count
                                                     cur = System.Text.RegularExpressions.Regex.Replace(cur, idPattern, idEval)
                                                     For Each np As String In namePatterns
                                                         cur = System.Text.RegularExpressions.Regex.Replace(cur, np, nameEval)
                                                     Next
                                                     Return cur
                                                 End Function

Try
    Dim rd As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(transcriptJson))
    rd.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    Dim tr As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rd)
    Dim roleLabel As New System.Collections.Generic.Dictionary(Of String, String)
    roleLabel("AGENT") = "상담원"
    roleLabel("CUSTOMER") = "고객"
    roleLabel("UNKNOWN") = "알수없음"
    Dim segsOut As New Newtonsoft.Json.Linq.JArray()
    Dim lines As New System.Collections.Generic.List(Of String)
    For Each segTok As Newtonsoft.Json.Linq.JToken In tr("segments").Children()
        Dim seg As Newtonsoft.Json.Linq.JObject = CType(segTok.DeepClone(), Newtonsoft.Json.Linq.JObject)
        Dim masked As String = maskText(seg.Value(Of String)("text"))
        seg("text") = masked
        segsOut.Add(seg)
        lines.Add("[" & roleLabel(seg.Value(Of String)("speaker")) & "] " & masked)
    Next
    maskedFullText = String.Join(vbLf, lines)

    Dim trOut As New Newtonsoft.Json.Linq.JObject()
    trOut("full_text") = maskedFullText
    trOut("segments") = segsOut
    If tr("speaker_confidence") Is Nothing Then
        trOut("speaker_confidence") = Newtonsoft.Json.Linq.JValue.CreateNull()
    Else
        trOut("speaker_confidence") = tr("speaker_confidence").DeepClone()
    End If
    Dim countsOut As New Newtonsoft.Json.Linq.JObject()
    For Each ck As String In New String() {"phone", "rrn", "card", "account", "email", "name", "address", "password", "birth", "id"}
        countsOut(ck) = counts(ck)
    Next
    Dim piiOut As New Newtonsoft.Json.Linq.JObject()
    piiOut("masked") = True
    piiOut("counts") = countsOut
    Dim outObj As New Newtonsoft.Json.Linq.JObject()
    outObj("transcript") = trOut
    outObj("pii") = piiOut
    maskedJson = outObj.ToString(Newtonsoft.Json.Formatting.None)
Catch ex As System.Exception
    maskError = "마스킹 실패(" & ex.GetType().Name & ")"
    maskedJson = ""
    maskedFullText = ""
End Try
