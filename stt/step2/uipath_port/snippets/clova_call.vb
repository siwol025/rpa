' Step6: CLOVA Speech STT 호출  (Python: clova_stt.transcribe — load_config, check_audio, build_params, call_clova, _poll)
' In : audioPath(String) 음성 파일 경로, configPath(String) config.json 경로 (clova_invoke_url, clova_secret_key, stt{...})
' Out: sttJson(String) 성공 시 CLOVA 응답 원본(result=COMPLETED, segments 있음),
'      sttStage(String) 실패 단계("INPUT"/"STT"), sttError(String) 실패 사유 (성공이면 둘 다 ""),
'      resultJson(String; {"sttJson": 객체|null, "sttStage", "sttError"} — 테스트 비교용)
' Secret Key 는 결과·로그·오류 메시지 어디에도 넣지 않는다.
sttJson = ""
sttStage = ""
sttError = ""
resultJson = ""

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
' Python 의 truthiness (segments/token 판정용)
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
' JSON 본문 파싱. 반환: "" 성공(parsedObj 에 객체) / "JSONDecodeError" JSON 이 아님 / "AttributeError" JSON 이지만 객체가 아님
Dim parsedObj As Newtonsoft.Json.Linq.JObject = Nothing
Dim parseBody As System.Func(Of String, String) = Function(body As String) As String
                                                      parsedObj = Nothing
                                                      Dim tk As Newtonsoft.Json.Linq.JToken = Nothing
                                                      Dim lbl As String = ""
                                                      Try
                                                          Dim rdr As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(body))
                                                          rdr.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
                                                          tk = Newtonsoft.Json.Linq.JToken.ReadFrom(rdr)
                                                          If rdr.Read() Then lbl = "JSONDecodeError"
                                                      Catch jex As Newtonsoft.Json.JsonException
                                                          lbl = "JSONDecodeError"
                                                      End Try
                                                      If lbl = "" Then
                                                          If tk.Type <> Newtonsoft.Json.Linq.JTokenType.Object Then
                                                              lbl = "AttributeError"
                                                          Else
                                                              parsedObj = CType(tk, Newtonsoft.Json.Linq.JObject)
                                                          End If
                                                      End If
                                                      Return lbl
                                                  End Function

Dim cfg As Newtonsoft.Json.Linq.JObject = Nothing
Dim invokeUrl As String = ""
Dim secretKey As String = ""

' 1) 설정 읽기 (Python: load_config) — 읽을 수 없으면 INPUT 단계
Dim cfgText As String = Nothing
Try
    cfgText = System.IO.File.ReadAllText(configPath)
Catch ex As System.Exception
    cfgText = Nothing
End Try
If cfgText Is Nothing Then
    sttStage = "INPUT"
    sttError = "config.json을 읽을 수 없음(경로/JSON 형식 확인)"
Else
    Dim cfgLabel As String = parseBody(cfgText)
    If cfgLabel = "JSONDecodeError" Then
        sttStage = "INPUT"
        sttError = "config.json을 읽을 수 없음(경로/JSON 형식 확인)"
    ElseIf cfgLabel = "AttributeError" Then
        sttStage = "STT"
        sttError = "호출 오류(AttributeError)"
    Else
        cfg = parsedObj
    End If
End If
If sttError = "" Then
    For Each ck As String In New String() {"clova_invoke_url", "clova_secret_key"}
        Dim ct As Newtonsoft.Json.Linq.JToken = cfg(ck)
        Dim cv As String = ""
        If truthy(ct) Then cv = pyStr(ct)
        If cv = "" OrElse cv.StartsWith("여기에_", System.StringComparison.Ordinal) Then
            If sttError = "" Then
                sttStage = "INPUT"
                sttError = "config.json의 " & ck & " 값이 비어 있음"
            End If
        ElseIf ck = "clova_invoke_url" Then
            invokeUrl = cv
        Else
            secretKey = cv
        End If
    Next
End If

' 2) 음성 파일 확인 (Python: check_audio)
If sttError = "" Then
    If String.IsNullOrEmpty(audioPath) OrElse Not System.IO.File.Exists(audioPath) Then
        sttStage = "INPUT"
        sttError = "음성 파일이 없음"
    ElseIf New System.IO.FileInfo(audioPath).Length = 0 Then
        sttStage = "INPUT"
        sttError = "빈 파일(0 byte)"
    Else
        Dim allowedExt As New System.Collections.Generic.HashSet(Of String)(New String() {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4"})
        If Not allowedExt.Contains(System.IO.Path.GetExtension(audioPath).ToLowerInvariant()) Then
            sttStage = "INPUT"
            sttError = "지원하지 않는 파일 형식"
        End If
    End If
End If

' 3) 호출 (Python: build_params, call_clova, _poll)
If sttError = "" Then
    Try
        Dim stt As Newtonsoft.Json.Linq.JObject = TryCast(cfg("stt"), Newtonsoft.Json.Linq.JObject)
        If stt Is Nothing Then stt = New Newtonsoft.Json.Linq.JObject()
        Dim opt As System.Func(Of String, Newtonsoft.Json.Linq.JToken, Newtonsoft.Json.Linq.JToken) = Function(key As String, dflt As Newtonsoft.Json.Linq.JToken) As Newtonsoft.Json.Linq.JToken
                                                                                                             If stt(key) Is Nothing Then Return dflt
                                                                                                             Return stt(key).DeepClone()
                                                                                                         End Function
        Dim diar As New Newtonsoft.Json.Linq.JObject()
        diar("enable") = True
        diar("speakerCountMin") = opt("speaker_count_min", 2)
        diar("speakerCountMax") = opt("speaker_count_max", 2)
        Dim prm As New Newtonsoft.Json.Linq.JObject()
        prm("language") = opt("language", "ko-KR")
        prm("completion") = opt("completion", "sync")
        prm("diarization") = diar
        prm("noiseFiltering") = opt("noise_filtering", True)
        prm("fullText") = True
        Dim paramsJson As String = prm.ToString(Newtonsoft.Json.Formatting.None)

        Dim baseUrl As String = invokeUrl.TrimEnd("/"c)
        Dim client As New System.Net.Http.HttpClient()
        client.Timeout = System.TimeSpan.FromSeconds(300)

        Dim upReq As New System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Post, baseUrl & "/recognizer/upload")
        upReq.Headers.Add("X-CLOVASPEECH-API-KEY", secretKey)
        Dim mp As New System.Net.Http.MultipartFormDataContent()
        Dim mediaPart As New System.Net.Http.ByteArrayContent(System.IO.File.ReadAllBytes(audioPath))
        Dim mimeByExt As New System.Collections.Generic.Dictionary(Of String, String)
        mimeByExt(".wav") = "audio/wav"
        mimeByExt(".mp3") = "audio/mpeg"
        mimeByExt(".m4a") = "audio/mp4"
        mimeByExt(".mp4") = "audio/mp4"
        mimeByExt(".aac") = "audio/aac"
        mimeByExt(".ogg") = "audio/ogg"
        mimeByExt(".flac") = "audio/flac"
        mediaPart.Headers.ContentType = New System.Net.Http.Headers.MediaTypeHeaderValue(mimeByExt(System.IO.Path.GetExtension(audioPath).ToLowerInvariant()))
        ' requests 와 같게 따옴표가 붙은 name/filename 을 직접 지정 (.NET 기본값은 따옴표가 없음)
        mediaPart.Headers.ContentDisposition = New System.Net.Http.Headers.ContentDispositionHeaderValue("form-data")
        mediaPart.Headers.ContentDisposition.Name = Chr(34) & "media" & Chr(34)
        mediaPart.Headers.ContentDisposition.FileName = Chr(34) & System.IO.Path.GetFileName(audioPath) & Chr(34)
        mp.Add(mediaPart)
        Dim pj As New System.Net.Http.StringContent(paramsJson, System.Text.Encoding.UTF8)
        pj.Headers.ContentType = New System.Net.Http.Headers.MediaTypeHeaderValue("application/json")
        pj.Headers.ContentDisposition = New System.Net.Http.Headers.ContentDispositionHeaderValue("form-data")
        pj.Headers.ContentDisposition.Name = Chr(34) & "params" & Chr(34)
        mp.Add(pj)
        upReq.Content = mp
        Dim upResp As System.Net.Http.HttpResponseMessage = client.SendAsync(upReq).Result
        Dim data As Newtonsoft.Json.Linq.JObject = Nothing
        If CInt(upResp.StatusCode) >= 400 Then
            sttStage = "STT"
            sttError = "호출 오류(HTTP " & CInt(upResp.StatusCode).ToString() & ")"
        Else
            Dim pe As String = parseBody(upResp.Content.ReadAsStringAsync().Result)
            If pe <> "" Then
                sttStage = "STT"
                sttError = "호출 오류(" & pe & ")"
            Else
                data = parsedObj
            End If
        End If

        ' 결과가 아직 처리 중이고 token 이 있으면 폴링
        If sttError = "" Then
            Dim resTok As Newtonsoft.Json.Linq.JToken = data("result")
            Dim resText As String = ""
            If resTok IsNot Nothing AndAlso resTok.Type = Newtonsoft.Json.Linq.JTokenType.String Then resText = CStr(CType(resTok, Newtonsoft.Json.Linq.JValue).Value)
            If Not (resText = "COMPLETED" OrElse resText = "FAILED") AndAlso truthy(data("token")) Then
                Dim interval As Double = 5.0
                If stt("poll_interval_sec") IsNot Nothing Then interval = stt("poll_interval_sec").ToObject(Of Double)()
                Dim maxCount As Integer = 60
                If stt("poll_max_count") IsNot Nothing Then maxCount = CInt(System.Math.Truncate(stt("poll_max_count").ToObject(Of Double)()))
                Dim polled As Newtonsoft.Json.Linq.JObject = Nothing
                Dim n As Integer = 0
                Do While n < maxCount AndAlso polled Is Nothing AndAlso sttError = ""
                    Dim getReq As New System.Net.Http.HttpRequestMessage(System.Net.Http.HttpMethod.Get, baseUrl & "/recognizer/" & pyStr(data("token")))
                    getReq.Headers.Add("X-CLOVASPEECH-API-KEY", secretKey)
                    Dim cts As New System.Threading.CancellationTokenSource(30000)
                    Dim gResp As System.Net.Http.HttpResponseMessage = client.SendAsync(getReq, cts.Token).Result
                    If CInt(gResp.StatusCode) >= 400 Then
                        sttStage = "STT"
                        sttError = "호출 오류(HTTP " & CInt(gResp.StatusCode).ToString() & ")"
                    Else
                        Dim pe2 As String = parseBody(gResp.Content.ReadAsStringAsync().Result)
                        If pe2 <> "" Then
                            sttStage = "STT"
                            sttError = "호출 오류(" & pe2 & ")"
                        Else
                            Dim r2 As Newtonsoft.Json.Linq.JToken = parsedObj("result")
                            Dim r2Text As String = ""
                            If r2 IsNot Nothing AndAlso r2.Type = Newtonsoft.Json.Linq.JTokenType.String Then r2Text = CStr(CType(r2, Newtonsoft.Json.Linq.JValue).Value)
                            If r2Text = "COMPLETED" OrElse r2Text = "FAILED" Then
                                polled = parsedObj
                            Else
                                System.Threading.Thread.Sleep(CInt(interval * 1000.0))
                            End If
                        End If
                    End If
                    n = n + 1
                Loop
                If sttError = "" Then
                    If polled Is Nothing Then
                        sttStage = "STT"
                        sttError = "결과 대기 시간 초과(폴링 한도)"
                    Else
                        data = polled
                    End If
                End If
            End If
        End If

        ' 결과 확인 (Python: transcribe)
        If sttError = "" Then
            Dim fin As Newtonsoft.Json.Linq.JToken = data("result")
            If fin Is Nothing OrElse fin.Type <> Newtonsoft.Json.Linq.JTokenType.String OrElse CStr(CType(fin, Newtonsoft.Json.Linq.JValue).Value) <> "COMPLETED" Then
                sttStage = "STT"
                If data("message") Is Nothing Then
                    sttError = "CLOVA 처리 실패: 원인 불명"
                Else
                    sttError = "CLOVA 처리 실패: " & pyStr(data("message"))
                End If
            ElseIf Not truthy(data("segments")) Then
                sttStage = "STT"
                sttError = "인식된 발화가 없음(무음/빈 음성)"
            Else
                sttJson = data.ToString(Newtonsoft.Json.Formatting.None)
            End If
        End If
    Catch ex As System.Exception
        ' 키/URL 이 메시지에 섞이지 않도록 종류만 기록
        Dim inner As System.Exception = ex
        Do While inner.InnerException IsNot Nothing
            inner = inner.InnerException
        Loop
        sttJson = ""
        sttStage = "STT"
        sttError = "호출 오류(" & inner.GetType().Name & ")"
    End Try
End If

Dim resultObj As New Newtonsoft.Json.Linq.JObject()
If sttJson <> "" Then
    Dim rdOut As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(sttJson))
    rdOut.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
    resultObj("sttJson") = Newtonsoft.Json.Linq.JObject.Load(rdOut)
Else
    resultObj("sttJson") = Newtonsoft.Json.Linq.JValue.CreateNull()
End If
resultObj("sttStage") = sttStage
resultObj("sttError") = sttError
resultJson = resultObj.ToString(Newtonsoft.Json.Formatting.None)
