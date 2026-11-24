' (Step5 테스트 전용) 시나리오 메타 JSON 을 변수로 풀어 준다.
' In : metaJson(String) {"fileName","seq","nowIso","promptVersion","sttEngine","genaiModel","sttError"}
' Out: fileName, nowIso, promptVersion, sttEngine, genaiModel, sttStage, sttError (String), seq (Int32)
Dim rdMeta As New Newtonsoft.Json.JsonTextReader(New System.IO.StringReader(metaJson))
rdMeta.DateParseHandling = Newtonsoft.Json.DateParseHandling.None
Dim metaObj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Load(rdMeta)
fileName = metaObj.Value(Of String)("fileName")
seq = metaObj.Value(Of Integer)("seq")
nowIso = metaObj.Value(Of String)("nowIso")
promptVersion = metaObj.Value(Of String)("promptVersion")
sttEngine = metaObj.Value(Of String)("sttEngine")
genaiModel = metaObj.Value(Of String)("genaiModel")
sttStage = metaObj.Value(Of String)("sttStage")
sttError = metaObj.Value(Of String)("sttError")
