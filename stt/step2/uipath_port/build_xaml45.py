# -*- coding: utf-8 -*-
"""
Step4(마스킹)·Step5(최종 JSON 조립) 테스트 XAML 과 Main_Step1to5.xaml 생성.
build_xaml.py 의 main() 이 불러 쓴다 (build_xaml.py 의 조각 함수를 그대로 사용).
"""
import os
import re

import common as C
from build_xaml import (HEADER_TEST, PATHS, RETRY_VARS, S, VALIDATE_VARS, add_refs, assign, finalize_block, foreach, if_, invoke_code,
                        log, make_dir, on_valid_else_error, read_text, seq, str_list, throw, try_catch, var, wrap, write_text)

MASK_ARGS = [("In", S, "transcriptJson", "transcriptJson"), ("Out", S, "maskedJson", "maskedJson"),
             ("Out", S, "maskedFullText", "maskedFullText"), ("Out", S, "maskError", "maskError")]
MASK_VARS = [var(S, "transcriptJson"), var(S, "maskedJson"), var(S, "maskedFullText"), var(S, "maskError")]
META_ARGS = [("In", S, "metaJson", "metaJson"), ("Out", S, "fileName", "fileName"), ("Out", "x:Int32", "seq", "seq"), ("Out", S, "nowIso", "nowIso"),
             ("Out", S, "promptVersion", "promptVersion"), ("Out", S, "sttEngine", "sttEngine"), ("Out", S, "genaiModel", "genaiModel"),
             ("Out", S, "sttStage", "sttStage"), ("Out", S, "sttError", "sttError")]
NOW_KST = """DateTime.UtcNow.AddHours(9).ToString("yyyy-MM-dd'T'HH:mm:ss", System.Globalization.CultureInfo.InvariantCulture) & "+09:00" """.strip()


def assemble_block(masked, analysis, stt_stage, stt_error, file_name, seq_expr, now_iso, prompt_version, stt_engine, genai_model):
    return invoke_code("최종 JSON 조립·상태 판정 (Invoke Code)", "assemble_result.vb", [
        ("In", S, "maskedJson", masked), ("In", S, "analysisJson", analysis), ("In", S, "sttStage", stt_stage), ("In", S, "sttError", stt_error), ("In", S, "fileName", file_name),
        ("In", "x:Int32", "seq", seq_expr), ("In", S, "nowIso", now_iso), ("In", S, "promptVersion", prompt_version),
        ("In", S, "sttEngine", stt_engine), ("In", S, "genaiModel", genai_model),
        ("Out", S, "docJson", "docJson"), ("Out", S, "assembleError", "assembleError")])


def step4(cases):
    inner = seq("한 건 처리", [
        read_text("마스킹 전 전사 JSON 읽기", 'System.IO.Path.Combine(testDir, "step4", caseName & ".json")', "transcriptJson"),
        invoke_code("개인정보 마스킹 (Invoke Code)", "mask_pii.vb", MASK_ARGS),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step4")'),
        write_text("마스킹 결과 JSON 저장", 'System.IO.Path.Combine(outDir, "step4", caseName & ".json")', "maskedJson"),
        log("로그", 'caseName & " 마스킹 완료 (전문 " & maskedFullText.Length.ToString() & "자, 오류: " & maskError & ")"'),
    ], variables=MASK_VARS)
    body = seq("Step4 마스킹 테스트", [foreach(S, "케이스별 반복", "cases", "caseName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "cases", str_list(cases))])
    return wrap(add_refs(HEADER_TEST), "Step4_Mask_Test", body)


def step5(scenarios):
    inner = seq("시나리오 처리", [
        read_text("마스킹 결과 읽기", 'System.IO.Path.Combine(testDir, "step5", scName, "masked.json")', "maskedJson"),
        read_text("분석 결과(Step3 결과) 읽기", 'System.IO.Path.Combine(testDir, "step5", scName, "analysis.json")', "analysisJson"),
        read_text("메타 정보 읽기", 'System.IO.Path.Combine(testDir, "step5", scName, "meta.json")', "metaJson"),
        invoke_code("메타 JSON 풀기 (Invoke Code, 테스트 전용)", "read_meta.vb", META_ARGS),
        assemble_block("maskedJson", "analysisJson", "sttStage", "sttError", "fileName", "seq", "nowIso", "promptVersion", "sttEngine", "genaiModel"),
        if_("조립 오류?", 'assembleError <> ""', throw("조립 실패", 'New System.InvalidOperationException(assembleError & " (시나리오: " & scName & ")")')),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step5")'),
        write_text("최종 JSON 저장", 'System.IO.Path.Combine(outDir, "step5", scName & ".json")', "docJson"),
        log("로그", 'scName & " 조립 완료 (" & docJson.Length.ToString() & "자)"'),
    ], variables=[var(S, "maskedJson"), var(S, "analysisJson"), var(S, "metaJson"), var(S, "fileName"), var("x:Int32", "seq", "0"), var(S, "nowIso"),
                  var(S, "promptVersion"), var(S, "sttEngine"), var(S, "genaiModel"), var(S, "sttStage"), var(S, "sttError"), var(S, "docJson"), var(S, "assembleError")])
    body = seq("Step5 최종 JSON 조립 테스트", [foreach(S, "시나리오별 반복", "scenarios", "scName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "scenarios", str_list(scenarios))])
    return wrap(add_refs(HEADER_TEST), "Step5_Assemble_Test", body)


def main_step1to5():
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
    header = add_refs(header)

    call = try_catch("모델 호출 (예외도 실패로 취급)", seq("호출", [connector]),
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
    per = seq("한 건 처리", [
        assign(S, "nowIso", NOW_KST, "처리 시각(KST) 기록"),
        read_text("마스킹 전 전사 JSON 읽기 (STT 파싱 결과)", 'baseDir & sid & "_transcript.json"', "transcriptJson"),
        invoke_code("개인정보 마스킹 (Invoke Code)", "mask_pii.vb", MASK_ARGS),
        if_("마스킹 실패?", 'maskError <> ""', throw("마스킹 실패", 'New System.InvalidOperationException(maskError & " (세션: " & sid & ")")')),
        invoke_code("프롬프트 조립 (Invoke Code)", "build_prompt.vb", [
            ("In", S, "promptText", "promptText"), ("In", S, "transcriptText", "maskedFullText"),
            ("Out", S, "systemPrompt", "systemPrompt"), ("Out", S, "userPrompt", "userPrompt"), ("Out", S, "buildError", "buildError")]),
        if_("프롬프트 조립 실패?", 'buildError <> ""', throw("프롬프트 조립 실패", 'New System.InvalidOperationException(buildError & " (세션: " & sid & ")")')),
        write_text("조립한 system 프롬프트 저장 (Python 결과와 비교용)", 'baseDir & "ui_" & sid & "_system.txt"', "systemPrompt"),
        write_text("조립한 user 프롬프트 저장 (Python 결과와 비교용)", 'baseDir & "ui_" & sid & "_user.txt"', "userPrompt"),
        foreach("x:Int32", "시도 반복 (최초 1회 + 재시도)", "Enumerable.Range(0, maxRetry + 1)", "attempt", attempt_body),
        finalize_block(),
        assemble_block("maskedJson", "finalJson", '""', '""', 'sid & ".wav"', "sessions.IndexOf(sid) + 1", "nowIso", "promptVersion", "sttEngine", "genaiModel"),
        if_("조립 실패?", 'assembleError <> ""', throw("결과 조립 실패", 'New System.InvalidOperationException(assembleError & " (세션: " & sid & ")")')),
        write_text("마지막 모델 응답 원문 저장", 'baseDir & sid & "_response.txt"', "llmResponse"),
        write_text("분석 결과 저장 (result/error/retry_count)", 'baseDir & sid & "_analysis.json"', "finalJson"),
        write_text("최종 결과 JSON 저장 (call_schema v1.0)", 'baseDir & sid & "_result.json"', "docJson"),
        log("완료 로그", 'sid & " 완료 — 모델 성공: " & isDone.ToString() & If(isDone, ", 재시도: " & attemptUsed.ToString(), "") & ", 최종 JSON " & docJson.Length.ToString() & "자"'),
    ], variables=[var(S, "nowIso"), var(S, "systemPrompt"), var(S, "userPrompt"), var(S, "buildError"), var(S, "llmResponse"),
                  var("x:Boolean", "callFailed", "False"), var(S, "docJson"), var(S, "assembleError")] + MASK_VARS + VALIDATE_VARS[1:] + RETRY_VARS)
    body = seq("Main Sequence - GenAI (마스킹 → 프롬프트 → 호출·검증·재시도 → 최종 JSON)", [
        read_text("프롬프트 템플릿 읽기", "promptPath", "promptText"),
        foreach(S, "세션별 반복", "sessions", "sid", per)],
        variables=[
            var(S, "baseDir", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "genai_test") & System.IO.Path.DirectorySeparatorChar'),
            var(S, "promptPath", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "prompts", "prompt_v1_1.txt")'),
            var("x:Int32", "maxRetry", "2"), var(S, "promptText"),
            var(S, "promptVersion", '"v1_1"'), var(S, "sttEngine", '"clova-speech"'), var(S, "genaiModel", '"gpt-6-luna"'),
            var("scg:List(x:String)", "sessions", str_list(C.SIDS))])
    return wrap(header, "Main_Step1to5", body)


def run_all():
    """Step1~5 테스트를 차례로 실행하고 마지막에 실제 모델 호출 흐름(Main_Step1to5)을 실행한다. 한 번만 Run File 하면 된다."""
    def invoke(display, name):
        return '<ui:InvokeWorkflowFile DisplayName="%s" UnSafe="False" WorkflowFileName="%s" />' % (display, name)
    steps = [
        ("Step1 프롬프트 조립 테스트", "Step1_BuildPrompt_Test.xaml"),
        ("Step2 응답 검증 테스트", "Step2_Validate_Test.xaml"),
        ("Step3 재시도 테스트", "Step3_Retry_Test.xaml"),
        ("Step4 마스킹 테스트", "Step4_Mask_Test.xaml"),
        ("Step5 최종 JSON 조립 테스트", "Step5_Assemble_Test.xaml"),
        ("Step6 STT 호출 테스트 (fake_clova.py 실행 필요)", "Step6_SttCall_Test.xaml"),
        ("Step7 STT 응답 파싱 테스트", "Step7_Parse_Test.xaml"),
        ("Step8 폴더 순회·파일 이동 테스트 (fake_clova.py 실행 필요)", "Step8_Folder_Test.xaml"),
        ("전체 흐름 (저장된 STT 응답 사용, 실제 모델 호출 5건 이상): Main_Step1to7", "Main_Step1to7.xaml"),
    ]
    children = [log("시작 로그", '"=== Run_All 시작: Step1~8 테스트 → Main_Step1to7(모델 호출) ==="')]
    for display, name in steps:
        children.append(invoke(display, name))
        children.append(log("완료 로그", '"%s 완료"' % name))
    children.append(log("종료 로그", '"=== Run_All 끝. python compare_uipath.py --step all 과 --step main7 로 비교하세요 ==="'))
    return wrap(add_refs(HEADER_TEST), "Run_All", seq("Run_All - Step1~8 테스트와 전체 흐름", children))
