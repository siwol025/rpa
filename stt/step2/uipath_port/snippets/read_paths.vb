' Step8: 입출력 폴더 정하기  (Python: run_folder.resolve_folders)
' In : configPath(String) config.json 경로, baseDir(String) 기준 폴더(프로젝트 폴더)
' Out: inDir, outDir, doneDir, failedDir (String)
'      기본값은 baseDir\calls\in|out|done|failed. config.json 의 paths.input_dir/output_dir/done_dir/failed_dir 가 있으면 그 값을 쓴다.
'      상대 경로는 baseDir 기준, 절대 경로는 그대로. 값이 비었거나 "<"·"여기에_"로 시작(양식의 자리표시자)하거나 문자열이 아니면 기본값.
'      설정 파일이 없거나 읽을 수 없어도 기본값이다 (예외를 내지 않는다).
inDir = System.IO.Path.Combine(baseDir, "calls", "in")
outDir = System.IO.Path.Combine(baseDir, "calls", "out")
doneDir = System.IO.Path.Combine(baseDir, "calls", "done")
failedDir = System.IO.Path.Combine(baseDir, "calls", "failed")
Try
    If Not String.IsNullOrEmpty(configPath) AndAlso System.IO.File.Exists(configPath) Then
        Dim rd As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(System.IO.File.ReadAllText(configPath, System.Text.Encoding.UTF8)))
        rd.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
        Dim cfg As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rd)
        Dim pt As Newtonsoft.Json.Linq.JToken = cfg("paths")
        If pt IsNot Nothing AndAlso pt.Type = Newtonsoft.Json.Linq.JTokenType.Object Then
            Dim pick As System.Func(Of String, String, String) = Function(key As String, dflt As String) As String
                                                                    Dim tok As Newtonsoft.Json.Linq.JToken = pt(key)
                                                                    If tok Is Nothing OrElse tok.Type <> Newtonsoft.Json.Linq.JTokenType.String Then Return dflt
                                                                    Dim v As String = CStr(CType(tok, Newtonsoft.Json.Linq.JValue).Value).Trim()
                                                                    If v = "" OrElse v.StartsWith("<", System.StringComparison.Ordinal) OrElse v.StartsWith("여기에_", System.StringComparison.Ordinal) Then Return dflt
                                                                    If System.IO.Path.IsPathRooted(v) Then Return System.IO.Path.GetFullPath(v)
                                                                    Return System.IO.Path.GetFullPath(System.IO.Path.Combine(baseDir, v))
                                                                End Function
            inDir = pick("input_dir", inDir)
            outDir = pick("output_dir", outDir)
            doneDir = pick("done_dir", doneDir)
            failedDir = pick("failed_dir", failedDir)
        End If
    End If
Catch ex As System.Exception
    ' 설정을 읽지 못하면 기본값을 쓴다 (이미 위에서 정해 둠)
End Try
