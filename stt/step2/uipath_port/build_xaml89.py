# -*- coding: utf-8 -*-
"""
Step8: 입력 폴더 순회·결과 저장·파일 이동 XAML 생성.
  Main_Folder.xaml        운영용 (calls\\in → out / done / failed), 모델은 실제 Content Generation
  Step8_Folder_Test.xaml  같은 흐름에 테스트 설정(임시 실행 폴더, 가짜 CLOVA 서버, 모의 모델 응답) — 함수 하나로 두 파일을 만든다
build_xaml.py 의 main() 이 불러 쓴다.
"""
import os
import re

import common as C
from build_xaml import (RETRY_VARS, S, VALIDATE_VARS, add_refs, assign, finalize_block, foreach, if_, invoke_code, log, make_dir,
                        on_valid_else_error, read_text, seq, str_list, throw, try_catch, var, wrap, write_text)
from build_xaml45 import MASK_ARGS, MASK_VARS, NOW_KST, assemble_block
from build_xaml67 import CLOVA_ARGS, PARSE_ARGS, with_http

L = "scg:List(x:String)"


def log_warn(display, msg_expr):
    from build_xaml import esc
    return '<ui:LogMessage DisplayName="%s" Level="Warn" Message="[%s]" />' % (esc(display), esc(msg_expr))


def folder_flow(test):
    with open(os.path.join(C.UIPATH, "Main.xaml"), encoding="utf-8") as f:
        orig = f.read()
    m = re.search(r"<isactr:ConnectorActivity .*?</isactr:ConnectorActivity>", orig, flags=re.S)
    if not m:
        raise SystemExit("현재 Main.xaml 에서 Content Generation(ConnectorActivity)을 찾지 못했습니다.")
    connector = m.group(0)
    header = orig[:orig.index("<Sequence ")]
    header = re.sub(r' x:Class="[^"]*"', ' x:Class="@@CLASS@@"', header, count=1)
    header = header.replace(' sap2010:WorkflowViewState.IdRef="ActivityBuilder_1"', "")
    if "xmlns:s=" not in header:
        header = header.replace(" xmlns:sap=", ' xmlns:s="clr-namespace:System;assembly=System.Private.CoreLib" xmlns:sap=', 1)
    header = with_http(add_refs(header))

    # ---- 모델 호출: mock 이면 {파일 stem}.llm.txt 를 응답으로, 아니면 Content Generation
    real_call = if_("모의 응답이면 파일에서, 아니면 모델 호출", 'llmMode = "mock"',
                    assign(S, "llmResponse", 'If(System.IO.File.Exists(mockPath), System.IO.File.ReadAllText(mockPath), "")', "모의 모델 응답 읽기(없으면 빈 응답)"),
                    connector)
    call = try_catch("모델 호출 (예외도 실패로 취급)", seq("호출", [real_call]),
                     seq("호출 실패 처리", [assign("x:Boolean", "callFailed", "True", "호출 실패 표시"),
                                       assign(S, "lastError", '"응답 파싱 실패(" & exception.GetType().Name & ")"', "실패 사유 기록")]))
    attempt_body = if_("아직 성공 못 했으면 시도", "Not isDone", seq("시도", [
        assign("x:Boolean", "callFailed", "False", "호출 실패 표시 초기화"),
        assign(S, "llmResponse", "String.Empty", "이전 응답 비우기"),
        call,
        if_("호출이 성공했으면 검증", "Not callFailed", seq("검증", [
            invoke_code("응답 검증 (Invoke Code)", "validate_response.vb", [
                ("In", S, "responseText", "llmResponse"), ("Out", "x:Boolean", "isValid", "isValid"), ("Out", S, "errorText", "errorText"),
                ("Out", S, "cleanedJson", "cleanedJson"), ("Out", S, "resultJson", "resultJson")]),
            on_valid_else_error()]))]))

    # ---- 파일 하나 처리: STT → 파싱 → 마스킹 → 프롬프트 → 모델(재시도) → 조립. 예상 밖의 예외는 그 단계의 실패 건으로 기록
    chain = seq("STT → 분석 (예외는 실패 건으로 기록)", [
        invoke_code("STT 호출 (Invoke Code)", "clova_call.vb", CLOVA_ARGS),
        if_("STT 성공했으면 응답 파싱", 'sttError = ""', seq("응답 파싱", [
            invoke_code("STT 응답 파싱·화자 매핑 (Invoke Code)", "parse_clova.vb", PARSE_ARGS),
            if_("파싱 실패?", 'parseError <> ""', seq("STT 단계 실패로 기록", [
                assign(S, "sttStage", '"STT"', "실패 단계"), assign(S, "sttError", "parseError", "실패 사유")]))])),
        if_("STT·파싱 성공했으면 마스킹 → 분석", 'sttError = ""', seq("마스킹·분석", [
            assign(S, "phase", '"PII"', "현재 단계"),
            invoke_code("개인정보 마스킹 (Invoke Code)", "mask_pii.vb", MASK_ARGS),
            if_("마스킹 실패?", 'maskError <> ""', throw("마스킹 실패", 'New System.InvalidOperationException(maskError)')),
            assign(S, "phase", '"GENAI"', "현재 단계"),
            invoke_code("프롬프트 조립 (Invoke Code)", "build_prompt.vb", [
                ("In", S, "promptText", "promptText"), ("In", S, "transcriptText", "maskedFullText"),
                ("Out", S, "systemPrompt", "systemPrompt"), ("Out", S, "userPrompt", "userPrompt"), ("Out", S, "buildError", "buildError")]),
            if_("프롬프트 조립 실패?", 'buildError <> ""', throw("프롬프트 조립 실패", 'New System.InvalidOperationException(buildError)')),
            foreach("x:Int32", "시도 반복 (최초 1회 + 재시도)", "Enumerable.Range(0, maxRetry + 1)", "attempt", attempt_body),
            finalize_block()]))])
    guarded = try_catch("처리 중 예외 → 실패 건", chain,
                        seq("예외를 실패로 기록", [
                            assign(S, "sttStage", "phase", "실패 단계 = 진행 중이던 단계"),
                            assign(S, "sttError", '"처리 중 예외(" & exception.GetType().Name & ")"', "실패 사유")]))

    per_file = seq("파일 하나 처리", [
        assign(S, "nowIso", NOW_KST, "처리 시각(KST) 기록"),
        assign(S, "fileName", "System.IO.Path.GetFileName(filePath)", "파일 이름"),
        assign(S, "stem", "System.IO.Path.GetFileNameWithoutExtension(filePath)", "확장자 뺀 이름"),
        assign("x:Int32", "seq", "files.IndexOf(filePath) + 1", "순번(1부터)"),
        assign(S, "mockPath", 'System.IO.Path.Combine(mockDir, stem & ".llm.txt")', "모의 모델 응답 파일 경로"),
        assign(S, "phase", '"STT"', "현재 단계"),
        guarded,
        assemble_block("maskedJson", "finalJson", "sttStage", "sttError", "fileName", "seq", "nowIso", "promptVersion", "sttEngine", "genaiModel"),
        if_("조립 실패?", 'assembleError <> ""', throw("결과 조립 실패", 'New System.InvalidOperationException(assembleError & " (파일: " & fileName & ")")')),
        invoke_code("결과에서 상태·오류·재시도 횟수 읽기 (Invoke Code)", "doc_summary.vb", [
            ("In", S, "docJson", "docJson"), ("Out", S, "docStatus", "docStatus"), ("Out", S, "errStage", "errStage"),
            ("Out", S, "errReason", "errReason"), ("Out", "x:Int32", "retryCount", "retryCount")]),
        assign(S, "callId", 'nowIso.Substring(0, 4) & nowIso.Substring(5, 2) & nowIso.Substring(8, 2) & "_" & nowIso.Substring(11, 2) & nowIso.Substring(14, 2) & nowIso.Substring(17, 2) & "_" & seq.ToString("000")', "call_id"),
        invoke_code("결과 파일 이름 정하기 (Invoke Code)", "pick_dest.vb", [
            ("In", S, "destDir", "outDir"), ("In", S, "fileName", 'callId & ".json"'), ("Out", S, "destPath", "outPath")]),
        write_text("결과 JSON 저장 (out)", "outPath", "docJson"),
        assign("x:Boolean", "isFailed", 'docStatus = "FAILED"', "실패 건인지 (결과의 status 기준)"),
        invoke_code("원본 음성 이동 (Invoke Code)", "move_file.vb", [
            ("In", S, "srcPath", "filePath"), ("In", S, "destDir", "If(isFailed, failedDir, doneDir)"),
            ("Out", S, "movedPath", "movedPath"), ("Out", S, "moveError", "moveError")]),
        if_("이동 실패?", 'moveError <> ""', log_warn("이동 실패 경고", 'fileName & " " & moveError & " — 원본을 제자리에 둠"'),
            None),
        if_("실패 건 집계", "isFailed", assign("x:Int32", "failedCount", "failedCount + 1", "실패 건수"), assign("x:Int32", "doneCount", "doneCount + 1", "완료 건수")),
        log("파일 로그", 'fileName & " → " & If(isFailed, "failed", "done") & " [" & docStatus & "]" & If(errStage <> "", " " & errStage & ": " & errReason, "") & " (재시도 " & retryCount.ToString() & "회, 결과 " & System.IO.Path.GetFileName(outPath) & ")"'),
    ], variables=[var(S, "nowIso"), var(S, "fileName"), var(S, "stem"), var("x:Int32", "seq", "0"), var(S, "mockPath"), var(S, "phase", '"STT"'),
                  var(S, "audioPath"), var(S, "sttJson"), var(S, "sttStage"), var(S, "sttError"), var(S, "sttResultJson"),
                  var(S, "parseError"), var(S, "parseResultJson"), var(S, "systemPrompt"), var(S, "userPrompt"), var(S, "buildError"),
                  var(S, "llmResponse"), var("x:Boolean", "callFailed", "False"), var(S, "docJson"), var(S, "assembleError"),
                  var(S, "callId"), var(S, "outPath"), var("x:Boolean", "isFailed", "False"), var(S, "docStatus"), var(S, "errStage"), var(S, "errReason"), var("x:Int32", "retryCount", "0"), var(S, "movedPath"), var(S, "moveError"),
                  var(S, "transcriptJson")] + [v for v in MASK_VARS if 'Name="transcriptJson"' not in v] + VALIDATE_VARS[1:] + RETRY_VARS)
    # STT 호출용 입력 변수 이름(audioPath/configPath)을 현재 파일에 연결
    per_file = per_file.replace('x:Key="audioPath">[audioPath]<', 'x:Key="audioPath">[filePath]<')

    pre = []
    if test:
        pre = [invoke_code("테스트 폴더 초기화 (Invoke Code)", "reset_dirs.vb", [("In", S, "srcRoot", "srcRoot"), ("In", S, "runRoot", "runRoot"), ("Out", S, "resetError", "resetError")]),
               if_("초기화 실패?", 'resetError <> ""', throw("초기화 실패", "New System.InvalidOperationException(resetError)"))]
    body_children = pre + [
        make_dir("입력 폴더 준비", "inDir"), make_dir("결과 폴더 준비", "outDir"), make_dir("완료 폴더 준비", "doneDir"), make_dir("실패 폴더 준비", "failedDir"),
        read_text("프롬프트 템플릿 읽기", "promptPath", "promptText"),
        invoke_code("입력 파일 목록 (Invoke Code)", "list_inputs.vb", [("In", S, "inDir", "inDir"), ("Out", L, "fileList", "files")]),
        log("시작 로그", '"입력 폴더 " & inDir & " — 처리 대상 " & files.Count.ToString() & "개"'),
        foreach(S, "파일별 반복", "files", "filePath", per_file),
        log("요약 로그", '"처리 끝 — 완료(done) " & doneCount.ToString() & "건, 실패(failed) " & failedCount.ToString() & "건"'),
    ]
    cd = "System.Environment.CurrentDirectory"
    P = lambda *parts: "System.IO.Path.Combine(%s, %s)" % (cd, ", ".join('"%s"' % x for x in parts))
    if test:
        run_root = P("test_data_run", "step8")
        vars_ = [var(S, "srcRoot", P("test_data", "step8")), var(S, "runRoot", run_root), var(S, "resetError"),
                 var(S, "inDir", 'System.IO.Path.Combine(runRoot, "in")'), var(S, "outDir", 'System.IO.Path.Combine(runRoot, "out")'),
                 var(S, "doneDir", 'System.IO.Path.Combine(runRoot, "done")'), var(S, "failedDir", 'System.IO.Path.Combine(runRoot, "failed")'),
                 var(S, "mockDir", 'System.IO.Path.Combine(runRoot, "mock_llm")'), var(S, "configPath", 'System.IO.Path.Combine(runRoot, "config.json")'),
                 var(S, "llmMode", '"mock"'), var(S, "genaiModel", '"mock-rule-based"')]
        title, cls = "Step8 폴더 순회·파일 이동 테스트 (fake_clova.py 필요, 모델 호출 없음)", "Step8_Folder_Test"
    else:
        vars_ = [var(S, "inDir", P("calls", "in")), var(S, "outDir", P("calls", "out")), var(S, "doneDir", P("calls", "done")), var(S, "failedDir", P("calls", "failed")),
                 var(S, "mockDir", '""'), var(S, "configPath", 'If(Not String.IsNullOrEmpty(System.Environment.GetEnvironmentVariable("CLOVA_CONFIG")), System.Environment.GetEnvironmentVariable("CLOVA_CONFIG"), System.IO.Path.GetFullPath(System.IO.Path.Combine(System.Environment.CurrentDirectory, "..", "config.json")))'),
                 var(S, "llmMode", '"live"'), var(S, "genaiModel", '"gpt-6-luna"')]
        title, cls = "Main_Folder - calls\\in 의 음성 파일을 처리하고 out / done / failed 로 정리", "Main_Folder"
    vars_ += [var(S, "promptPath", P("prompts", "prompt_v1_1.txt")), var("x:Int32", "maxRetry", "2"), var(S, "promptText"),
              var(S, "promptVersion", '"v1_1"'), var(S, "sttEngine", '"clova-speech"'), var(L, "files"),
              var("x:Int32", "doneCount", "0"), var("x:Int32", "failedCount", "0")]
    body = seq(title, body_children, variables=vars_)
    return wrap(header, cls, body)
