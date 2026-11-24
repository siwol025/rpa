' Step1: 프롬프트 조립  (Python: analyze.build_prompt)
' In : promptText(String) 프롬프트 파일 전체, transcriptText(String) 마스킹된 전사본
' Out: systemPrompt, userPrompt, buildError(String, 성공이면 빈 문자열)
buildError = ""
systemPrompt = ""
userPrompt = ""
Dim keptLines As New System.Collections.Generic.List(Of String)
For Each rawLine As String In System.Text.RegularExpressions.Regex.Split(If(promptText, ""), "\r\n|\n|\r")
    ' 설명용 '#' 줄 제외 (Python: not l.lstrip().startswith("#"))
    If Not rawLine.TrimStart().StartsWith("#", System.StringComparison.Ordinal) Then keptLines.Add(rawLine)
Next
Dim promptBody As String = String.Join(vbLf, keptLines)
Dim blockMatch As System.Text.RegularExpressions.Match = System.Text.RegularExpressions.Regex.Match(promptBody, "\[SYSTEM\](.*?)\[USER TEMPLATE\](.*)", System.Text.RegularExpressions.RegexOptions.Singleline)
If Not blockMatch.Success Then
    buildError = "prompt 파일에 [SYSTEM]/[USER TEMPLATE] 블록이 없음"
Else
    systemPrompt = blockMatch.Groups(1).Value.Trim()
    userPrompt = blockMatch.Groups(2).Value.Trim().Replace("{{TRANSCRIPT}}", If(transcriptText, ""))
End If
