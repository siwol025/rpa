# -*- coding: utf-8 -*-
"""
UiPath 에 넣을 VB 코드 조각(snippets\\*.vb)을 이 PC에서 그대로 컴파일·실행해 Python 정답과 비교한다.

  python vb_check.py            # 컴파일 + Step1~3 실행 + 비교

- UiPath 의 Invoke Code 에 들어가는 코드와 같은 파일을 쓴다 (build_xaml.py 가 같은 파일을 XAML 에 넣음).
- .NET Framework 의 vbc.exe + Newtonsoft.Json 10.0.3 으로 컴파일한다 (UiPath 런타임의 Newtonsoft 13.x 와 JObject API 가 같다).
- 이 도구가 검증하는 것: 코드 조각의 로직과 재시도 루프의 알고리즘. XAML 자체(액티비티 연결)는 Studio 실행으로 확인한다.
"""
import glob
import os
import subprocess
import sys

import common as C

VBC = glob.glob(os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Microsoft.NET", "Framework64", "v4.*", "vbc.exe"))
NEWTONSOFT = os.path.join(os.path.expanduser("~"), ".nuget", "packages", "newtonsoft.json", "10.0.3", "lib", "net45", "Newtonsoft.Json.dll")
WORK = os.path.join(os.environ.get("TEMP", "."), "uipath_vb_check")
OUT_VB = os.path.join(C.UIPATH, "test_data_out_vb")


def snippet(name):
    with open(os.path.join(C.HERE, "snippets", name), encoding="utf-8") as f:
        # 주석 줄은 그대로 둬도 되지만 harness 의 들여쓰기만 맞춘다
        return "".join("        " + l for l in f.read().splitlines(True))


TEMPLATE = r'''Option Explicit On
Option Strict On
Option Infer On
Imports System
Imports System.IO
Imports System.Text
Imports System.Collections.Generic
Imports System.Linq

Public Module Harness
    Public Sub BuildPromptSnippet(ByVal promptText As String, ByVal transcriptText As String, ByRef systemPrompt As String, ByRef userPrompt As String, ByRef buildError As String)
@@BUILD@@
    End Sub

    Public Sub ValidateSnippet(ByVal responseText As String, ByRef isValid As Boolean, ByRef errorText As String, ByRef cleanedJson As String, ByRef resultJson As String)
@@VALIDATE@@
    End Sub

    Public Sub FinalizeSnippet(ByVal isDone As Boolean, ByVal cleanedJson As String, ByVal lastError As String, ByVal maxRetry As Integer, ByVal attemptUsed As Integer, ByRef finalJson As String)
@@FINALIZE@@
    End Sub

    Public Sub MaskSnippet(ByVal transcriptJson As String, ByRef maskedJson As String, ByRef maskedFullText As String, ByRef maskError As String)
@@MASK@@
    End Sub

    Public Sub ReadMetaSnippet(ByVal metaJson As String, ByRef fileName As String, ByRef seq As Integer, ByRef nowIso As String, ByRef promptVersion As String, ByRef sttEngine As String, ByRef genaiModel As String, ByRef sttStage As String, ByRef sttError As String)
@@READMETA@@
    End Sub

    Public Sub AssembleSnippet(ByVal maskedJson As String, ByVal analysisJson As String, ByVal sttStage As String, ByVal sttError As String, ByVal fileName As String, ByVal seq As Integer, ByVal nowIso As String, ByVal promptVersion As String, ByVal sttEngine As String, ByVal genaiModel As String, ByRef docJson As String, ByRef assembleError As String)
@@ASSEMBLE@@
    End Sub

    Public Sub ClovaSnippet(ByVal audioPath As String, ByVal configPath As String, ByRef sttJson As String, ByRef sttStage As String, ByRef sttError As String, ByRef resultJson As String)
@@CLOVA@@
    End Sub

    Public Sub ParseSnippet(ByVal sttJson As String, ByRef transcriptJson As String, ByRef parseError As String, ByRef resultJson As String)
@@PARSE@@
    End Sub

    Public Sub ListInputsSnippet(ByVal inDir As String, ByRef fileList As System.Collections.Generic.List(Of String))
@@LIST@@
    End Sub

    Public Sub PickDestSnippet(ByVal destDir As String, ByVal fileName As String, ByRef destPath As String)
@@PICK@@
    End Sub

    Public Sub MoveFileSnippet(ByVal srcPath As String, ByVal destDir As String, ByRef movedPath As String, ByRef moveError As String)
@@MOVE@@
    End Sub

    Public Sub DocSummarySnippet(ByVal docJson As String, ByRef docStatus As String, ByRef errStage As String, ByRef errReason As String, ByRef retryCount As Integer)
@@DOCSUM@@
    End Sub

    Public Sub ReadPathsSnippet(ByVal configPath As String, ByVal baseDir As String, ByRef inDir As String, ByRef outDir As String, ByRef doneDir As String, ByRef failedDir As String)
@@READPATHS@@
    End Sub

    Private Function ReadT(ByVal p As String) As String
        Return File.ReadAllText(p, Encoding.UTF8)
    End Function

    Private Sub WriteT(ByVal p As String, ByVal s As String)
        Directory.CreateDirectory(Path.GetDirectoryName(p))
        File.WriteAllText(p, s, New UTF8Encoding(False))
    End Sub

    Public Function Main(ByVal args As String()) As Integer
        Dim testDir As String = args(0)
        Dim outDir As String = args(1)
        Dim maxRetry As Integer = 2

        ' ---- Step1: 프롬프트 조립
        For Each d As String In Directory.GetDirectories(Path.Combine(testDir, "step1"))
            Dim c As String = Path.GetFileName(d)
            Dim sp As String = "", up As String = "", be As String = ""
            BuildPromptSnippet(ReadT(Path.Combine(d, "prompt.txt")), ReadT(Path.Combine(d, "transcript.txt")), sp, up, be)
            WriteT(Path.Combine(outDir, "step1", c, "system.txt"), sp)
            WriteT(Path.Combine(outDir, "step1", c, "user.txt"), up)
            WriteT(Path.Combine(outDir, "step1", c, "error.txt"), be)
        Next

        ' ---- Step2: 응답 검증
        For Each f As String In Directory.GetFiles(Path.Combine(testDir, "step2"), "*.txt")
            Dim ok As Boolean = False
            Dim et As String = "", cj As String = "", rj As String = ""
            ValidateSnippet(ReadT(f), ok, et, cj, rj)
            WriteT(Path.Combine(outDir, "step2", Path.GetFileNameWithoutExtension(f) & ".json"), rj)
        Next

        ' ---- Step3: 재시도 루프 (Step3_Retry_Test.xaml 과 같은 알고리즘)
        For Each d As String In Directory.GetDirectories(Path.Combine(testDir, "step3"))
            Dim c As String = Path.GetFileName(d)
            Dim isDone As Boolean = False
            Dim lastError As String = "원인 불명"
            Dim attemptUsed As Integer = 0
            Dim cleanedFinal As String = ""
            For attempt As Integer = 0 To maxRetry
                If Not isDone Then
                    Dim resp As String = ReadT(Path.Combine(d, "attempt" & (attempt + 1).ToString() & ".txt"))
                    Dim ok As Boolean = False
                    Dim et As String = "", cj As String = "", rj As String = ""
                    ValidateSnippet(resp, ok, et, cj, rj)
                    If ok Then
                        isDone = True
                        cleanedFinal = cj
                        attemptUsed = attempt
                    Else
                        lastError = et
                    End If
                End If
            Next
            Dim fj As String = ""
            FinalizeSnippet(isDone, cleanedFinal, lastError, maxRetry, attemptUsed, fj)
            WriteT(Path.Combine(outDir, "step3", c & ".json"), fj)
        Next

        ' ---- Step4: 마스킹
        For Each f As String In Directory.GetFiles(Path.Combine(testDir, "step4"), "*.json")
            Dim mj As String = "", mf As String = "", merr As String = ""
            MaskSnippet(ReadT(f), mj, mf, merr)
            WriteT(Path.Combine(outDir, "step4", Path.GetFileName(f)), mj)
        Next

        ' ---- Step5: 최종 JSON 조립
        For Each d As String In Directory.GetDirectories(Path.Combine(testDir, "step5"))
            Dim c As String = Path.GetFileName(d)
            Dim fn As String = "", sq As Integer = 0, ni As String = "", pv As String = "", se As String = "", gm As String = "", sg As String = "", st As String = ""
            ReadMetaSnippet(ReadT(Path.Combine(d, "meta.json")), fn, sq, ni, pv, se, gm, sg, st)
            Dim dj As String = "", ae As String = ""
            AssembleSnippet(ReadT(Path.Combine(d, "masked.json")), ReadT(Path.Combine(d, "analysis.json")), sg, st, fn, sq, ni, pv, se, gm, dj, ae)
            If ae <> "" Then Console.WriteLine(c & ": " & ae)
            WriteT(Path.Combine(outDir, "step5", c & ".json"), dj)
            Dim ds As String = "", es As String = "", er As String = "", rc As Integer = 0
            DocSummarySnippet(dj, ds, es, er, rc)
            Dim so As New Newtonsoft.Json.Linq.JObject()
            so("docStatus") = ds
            so("errStage") = es
            so("errReason") = er
            so("retryCount") = rc
            WriteT(Path.Combine(outDir, "step5s", c & ".json"), so.ToString(Newtonsoft.Json.Formatting.None))
        Next

        ' ---- Step6: STT 호출 (가짜 CLOVA 서버)
        For Each d As String In Directory.GetDirectories(Path.Combine(testDir, "step6"))
            Dim c As String = Path.GetFileName(d)
            If c.StartsWith("_") Then Continue For
            Dim audio As String = ""
            For Each f As String In Directory.GetFiles(d)
                If Path.GetFileName(f).ToLowerInvariant().StartsWith("audio.") AndAlso audio = "" Then audio = f
            Next
            Dim sj As String = "", sg As String = "", se As String = "", rj As String = ""
            ClovaSnippet(audio, Path.Combine(d, "config.json"), sj, sg, se, rj)
            WriteT(Path.Combine(outDir, "step6", c & ".json"), rj)
        Next

        ' ---- Step7: STT 응답 파싱
        For Each f As String In Directory.GetFiles(Path.Combine(testDir, "step7"), "*.json")
            Dim tj As String = "", pe As String = "", rj As String = ""
            ParseSnippet(ReadT(f), tj, pe, rj)
            WriteT(Path.Combine(outDir, "step7", Path.GetFileName(f)), rj)
        Next

        ' ---- Step8b: 목록·이동 코드 조각 (실제 파일 시스템, 임시 폴더)
        For Each f As String In Directory.GetFiles(Path.Combine(testDir, "step8b"), "*.json")
            Dim cname As String = Path.GetFileNameWithoutExtension(f)
            Dim cj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Parse(ReadT(f))
            Dim work As String = Path.Combine(outDir, "step8b_work", cname)
            If Directory.Exists(work) Then Directory.Delete(work, True)
            Directory.CreateDirectory(work)
            Dim res As New Newtonsoft.Json.Linq.JObject()
            If CStr(cj("kind")) = "list" Then
                Directory.CreateDirectory(Path.Combine(work, "in"))
                For Each e As Newtonsoft.Json.Linq.JToken In cj("entries").Children()
                    Dim fp As String = Path.Combine(work, "in", CStr(e))
                    Directory.CreateDirectory(Path.GetDirectoryName(fp))
                    File.WriteAllText(fp, "x")
                Next
                Dim lst As New System.Collections.Generic.List(Of String)
                ListInputsSnippet(Path.Combine(work, "in"), lst)
                Dim arr As New Newtonsoft.Json.Linq.JArray()
                For Each p As String In lst
                    arr.Add(Path.GetFileName(p))
                Next
                res("files") = arr
            Else
                Dim srcName As String = CStr(cj("src"))
                Directory.CreateDirectory(Path.Combine(work, "src"))
                Dim srcExists As Boolean = True
                If cj("src_exists") IsNot Nothing Then srcExists = CBool(cj("src_exists"))
                If srcExists Then File.WriteAllText(Path.Combine(work, "src", srcName), "x")
                If cj("dest_entries").Type <> Newtonsoft.Json.Linq.JTokenType.Null Then
                    Directory.CreateDirectory(Path.Combine(work, "dest"))
                    For Each e As Newtonsoft.Json.Linq.JToken In cj("dest_entries").Children()
                        Dim ep As String = CStr(e)
                        If ep.EndsWith("/") Then
                            Directory.CreateDirectory(Path.Combine(work, "dest", ep))
                        Else
                            File.WriteAllText(Path.Combine(work, "dest", ep), "old")
                        End If
                    Next
                End If
                Dim destDir As String = Path.Combine(work, "dest")
                Dim pk As String = ""
                PickDestSnippet(destDir, srcName, pk)
                Dim mp As String = "", me2 As String = ""
                MoveFileSnippet(Path.Combine(work, "src", srcName), destDir, mp, me2)
                res("picked") = Path.GetFileName(pk)
                res("moved") = If(mp = "", "", Path.GetFileName(mp))
                res("error") = me2
                Dim listing As New System.Collections.Generic.List(Of String)
                If Directory.Exists(destDir) Then
                    For Each x As String In Directory.GetFileSystemEntries(destDir)
                        listing.Add(Path.GetFileName(x))
                    Next
                End If
                listing.Sort(StringComparer.Ordinal)
                Dim larr As New Newtonsoft.Json.Linq.JArray()
                For Each x As String In listing
                    larr.Add(x)
                Next
                res("dest_listing") = larr
                res("src_still_exists") = File.Exists(Path.Combine(work, "src", srcName))
            End If
            WriteT(Path.Combine(outDir, "step8b", cname & ".json"), res.ToString(Newtonsoft.Json.Formatting.None))
        Next
        ' ---- Step8d: 입출력 폴더를 config.json 의 paths 에서 읽는 코드 조각 (임시 폴더)
        For Each f As String In Directory.GetFiles(Path.Combine(testDir, "step8d"), "*.json")
            Dim cname As String = Path.GetFileNameWithoutExtension(f)
            Dim cj As Newtonsoft.Json.Linq.JObject = Newtonsoft.Json.Linq.JObject.Parse(ReadT(f))
            Dim baseDir As String = Path.GetFullPath(Path.Combine(outDir, "step8d_work", cname))
            If Directory.Exists(baseDir) Then Directory.Delete(baseDir, True)
            Directory.CreateDirectory(baseDir)
            Dim cfgPath As String = Path.Combine(baseDir, "config.json")
            Dim ctok As Newtonsoft.Json.Linq.JToken = cj("config")
            If ctok.Type = Newtonsoft.Json.Linq.JTokenType.String Then
                File.WriteAllText(cfgPath, CStr(CType(ctok, Newtonsoft.Json.Linq.JValue).Value), New UTF8Encoding(False))
            ElseIf ctok.Type <> Newtonsoft.Json.Linq.JTokenType.Null Then
                File.WriteAllText(cfgPath, ctok.ToString(Newtonsoft.Json.Formatting.None), New UTF8Encoding(False))
            End If
            Dim i1 As String = "", o1 As String = "", d1 As String = "", f1 As String = ""
            ReadPathsSnippet(cfgPath, baseDir, i1, o1, d1, f1)
            Dim res As New Newtonsoft.Json.Linq.JObject()
            res("inDir") = i1.Replace(baseDir, "<BASE>")
            res("outDir") = o1.Replace(baseDir, "<BASE>")
            res("doneDir") = d1.Replace(baseDir, "<BASE>")
            res("failedDir") = f1.Replace(baseDir, "<BASE>")
            WriteT(Path.Combine(outDir, "step8d", cname & ".json"), res.ToString(Newtonsoft.Json.Formatting.None))
        Next
        Return 0
    End Function
End Module
'''


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not VBC or not os.path.exists(NEWTONSOFT):
        print("컴파일러(vbc.exe) 또는 Newtonsoft.Json 10.0.3 을 찾지 못함 — 이 검사는 건너뜁니다.")
        sys.exit(2)
    if not os.path.isdir(C.TEST):
        print("test_data 가 없음: 먼저 python make_fixtures.py 를 실행하세요.")
        sys.exit(2)
    os.makedirs(WORK, exist_ok=True)
    src = TEMPLATE.replace("@@BUILD@@", snippet("build_prompt.vb")).replace("@@VALIDATE@@", snippet("validate_response.vb")).replace("@@FINALIZE@@", snippet("finalize_result.vb")).replace("@@MASK@@", snippet("mask_pii.vb")).replace("@@READMETA@@", snippet("read_meta.vb")).replace("@@ASSEMBLE@@", snippet("assemble_result.vb")).replace("@@CLOVA@@", snippet("clova_call.vb")).replace("@@PARSE@@", snippet("parse_clova.vb")).replace("@@LIST@@", snippet("list_inputs.vb")).replace("@@PICK@@", snippet("pick_dest.vb")).replace("@@MOVE@@", snippet("move_file.vb")).replace("@@DOCSUM@@", snippet("doc_summary.vb")).replace("@@READPATHS@@", snippet("read_paths.vb"))
    vb = os.path.join(WORK, "harness.vb")
    exe = os.path.join(WORK, "harness.exe")
    with open(vb, "w", encoding="utf-8-sig", newline="") as f:
        f.write(src)
    dll = os.path.join(WORK, "Newtonsoft.Json.dll")
    with open(NEWTONSOFT, "rb") as a, open(dll, "wb") as b:
        b.write(a.read())
    r = subprocess.run([VBC[-1], "/nologo", "/target:exe", "/utf8output", "/out:" + exe, "/r:" + dll, "/r:System.dll", "/r:System.Core.dll", "/r:System.Net.Http.dll", vb],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("컴파일:", "성공" if r.returncode == 0 else "실패")
    if r.stdout.strip():
        print(r.stdout.strip()[:3000])
    if r.stderr.strip():
        print(r.stderr.strip()[:1000])
    if r.returncode != 0:
        sys.exit(1)
    if os.path.isdir(OUT_VB):
        import shutil
        shutil.rmtree(OUT_VB)
    import fake_clova
    srv, state = fake_clova.start_server(8765, os.path.join(C.TEST, "step6", "_server", "raw_ok.json"))
    try:
        r = subprocess.run([exe, C.TEST, OUT_VB], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=WORK)
    finally:
        pass
    if r.returncode != 0:
        print("실행 실패:", r.stdout[-1500:], r.stderr[-1500:])
        sys.exit(1)
    bad = 0
    bad += C.report("Step1 프롬프트 조립 (VB vs Python)", C.compare_step1(OUT_VB))
    bad += C.report("Step2 응답 검증 (VB vs Python)", C.compare_step2(OUT_VB))
    bad += C.report("Step3 재시도 (VB vs Python)", C.compare_step3(OUT_VB))
    bad += C.report("Step4 마스킹 (VB vs Python)", C.compare_step4(OUT_VB))
    bad += C.report("Step5 최종 JSON 조립 (VB vs Python)", C.compare_step5(OUT_VB))
    bad += C.report("Step6 STT 호출 — 가짜 서버 (VB vs Python)", C.compare_step6(OUT_VB, fetch_log=lambda name: state.logs.get(name, [])))
    bad += C.report("Step7 STT 응답 파싱 (VB vs Python)", C.compare_step7(OUT_VB))
    bad += C.report("Step8b 파일 목록·이동 코드 (VB vs Python)", C.compare_step8b(OUT_VB))
    bad += C.report("Step8d 입출력 폴더를 설정에서 읽기 (VB vs Python)", C.compare_step8d(OUT_VB))
    bad += C.report("Step8c 결과 문서에서 상태·오류·재시도 읽기 (VB vs Python)", C.compare_step8c(OUT_VB))
    srv.shutdown()
    srv.server_close()
    print("\n총 불일치:", bad)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
