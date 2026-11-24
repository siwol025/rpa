# -*- coding: utf-8 -*-
"""
Step6(STT 호출)·Step7(STT 응답 파싱) 테스트 XAML 과, 음성 파일에서 시작하는 전체 흐름 Main_Step1to7.xaml 생성.
build_xaml.py 의 main() 이 불러 쓴다.
"""
import os
import re

import common as C
from build_xaml import (HEADER_TEST, PATHS, RETRY_VARS, S, VALIDATE_VARS, add_refs, assign, finalize_block, foreach, if_, invoke_code,
                        log, make_dir, on_valid_else_error, read_text, seq, str_list, throw, try_catch, var, wrap, write_text)
from build_xaml45 import MASK_ARGS, MASK_VARS, NOW_KST, assemble_block

CLOVA_ARGS = [("In", S, "audioPath", "audioPath"), ("In", S, "configPath", "configPath"), ("Out", S, "sttJson", "sttJson"),
              ("Out", S, "sttStage", "sttStage"), ("Out", S, "sttError", "sttError"), ("Out", S, "resultJson", "sttResultJson")]
PARSE_ARGS = [("In", S, "sttJson", "sttJson"), ("Out", S, "transcriptJson", "transcriptJson"), ("Out", S, "parseError", "parseError"),
              ("Out", S, "resultJson", "parseResultJson")]
# 모듈이 추가로 쓰는 어셈블리 (HttpClient)
EXTRA_ASM = "System.Net.Http"


def with_http(header):
    if "<AssemblyReference>%s</AssemblyReference>" % EXTRA_ASM in header:
        return header
    i = header.index("</sco:Collection>", header.index("<AssemblyReference>"))
    return header[:i] + "      <AssemblyReference>%s</AssemblyReference>\n    " % EXTRA_ASM + header[i:]


def step6(scenarios):
    inner = seq("시나리오 처리", [
        assign(S, "scDir", 'System.IO.Path.Combine(testDir, "step6", scName)', "시나리오 폴더"),
        assign(S, "audioPath", 'System.IO.Directory.GetFiles(scDir, "audio.*").FirstOrDefault()', "음성 파일 찾기(없으면 Nothing)"),
        assign(S, "configPath", 'System.IO.Path.Combine(scDir, "config.json")', "설정 파일 경로"),
        invoke_code("STT 호출 (Invoke Code, 가짜 CLOVA 서버)", "clova_call.vb", CLOVA_ARGS),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step6")'),
        write_text("결과 JSON 저장", 'System.IO.Path.Combine(outDir, "step6", scName & ".json")', "sttResultJson"),
        log("로그", 'scName & " → 단계: " & sttStage & " / 사유: " & sttError & " / 응답 " & sttJson.Length.ToString() & "자"'),
    ], variables=[var(S, "scDir"), var(S, "audioPath"), var(S, "configPath"), var(S, "sttJson"), var(S, "sttStage"), var(S, "sttError"), var(S, "sttResultJson")])
    body = seq("Step6 STT 호출 테스트 (fake_clova.py 가 실행 중이어야 함)", [foreach(S, "시나리오별 반복", "scenarios", "scName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "scenarios", str_list(scenarios))])
    return wrap(with_http(add_refs(HEADER_TEST)), "Step6_SttCall_Test", body)


def step7(cases):
    inner = seq("한 건 처리", [
        read_text("CLOVA 응답 읽기", 'System.IO.Path.Combine(testDir, "step7", caseName & ".json")', "sttJson"),
        invoke_code("STT 응답 파싱·화자 매핑 (Invoke Code)", "parse_clova.vb", PARSE_ARGS),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step7")'),
        write_text("결과 JSON 저장", 'System.IO.Path.Combine(outDir, "step7", caseName & ".json")', "parseResultJson"),
        log("로그", 'caseName & " → 오류: " & parseError & " / 전사 " & transcriptJson.Length.ToString() & "자"'),
    ], variables=[var(S, "sttJson"), var(S, "transcriptJson"), var(S, "parseError"), var(S, "parseResultJson")])
    body = seq("Step7 STT 응답 파싱 테스트", [foreach(S, "케이스별 반복", "cases", "caseName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "cases", str_list(cases))])
    return wrap(add_refs(HEADER_TEST), "Step7_Parse_Test", body)


def main_step1to7():
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

    # 음성 → STT: live 모드는 CLOVA 호출(무료 인식 시간 소모, 음성이 외부로 전송됨), saved 모드는 저장된 응답 파일을 사용
    get_stt = if_("STT 가져오기: live 이면 CLOVA 호출, 아니면 저장된 응답", 'sttMode = "live"',
                  seq("CLOVA 호출", [
                      assign(S, "audioPath", 'System.IO.Path.Combine(audioDir, sid & ".wav")', "음성 파일 경로"),
                      invoke_code("STT 호출 (Invoke Code)", "clova_call.vb", CLOVA_ARGS),
                      if_("성공했으면 응답 원본 보관", 'sttError = ""', write_text("CLOVA 응답 원본 저장", 'baseDir & sid & "_stt_live.json"', "sttJson"))]),
                  seq("저장된 응답 사용", [read_text("저장된 CLOVA 응답 읽기", 'baseDir & sid & "_stt_raw.json"', "sttJson")]))
    parse_block = if_("STT 성공했으면 응답 파싱", 'sttError = ""', seq("응답 파싱", [
        invoke_code("STT 응답 파싱·화자 매핑 (Invoke Code)", "parse_clova.vb", PARSE_ARGS),
        if_("파싱 실패?", 'parseError <> ""', seq("STT 단계 실패로 기록", [
            assign(S, "sttStage", '"STT"', "실패 단계"), assign(S, "sttError", "parseError", "실패 사유")]))]))
    analyze_chain = if_("STT·파싱이 성공했으면 마스킹 → 분석", 'sttError = ""', seq("마스킹·분석", [
        invoke_code("개인정보 마스킹 (Invoke Code)", "mask_pii.vb", [
            ("In", S, "transcriptJson", "transcriptJson"), ("Out", S, "maskedJson", "maskedJson"),
            ("Out", S, "maskedFullText", "maskedFullText"), ("Out", S, "maskError", "maskError")]),
        if_("마스킹 실패?", 'maskError <> ""', throw("마스킹 실패", 'New System.InvalidOperationException(maskError & " (세션: " & sid & ")")')),
        invoke_code("프롬프트 조립 (Invoke Code)", "build_prompt.vb", [
            ("In", S, "promptText", "promptText"), ("In", S, "transcriptText", "maskedFullText"),
            ("Out", S, "systemPrompt", "systemPrompt"), ("Out", S, "userPrompt", "userPrompt"), ("Out", S, "buildError", "buildError")]),
        if_("프롬프트 조립 실패?", 'buildError <> ""', throw("프롬프트 조립 실패", 'New System.InvalidOperationException(buildError & " (세션: " & sid & ")")')),
        write_text("조립한 system 프롬프트 저장", 'baseDir & "ui_" & sid & "_system.txt"', "systemPrompt"),
        write_text("조립한 user 프롬프트 저장", 'baseDir & "ui_" & sid & "_user.txt"', "userPrompt"),
        foreach("x:Int32", "시도 반복 (최초 1회 + 재시도)", "Enumerable.Range(0, maxRetry + 1)", "attempt", attempt_body),
        finalize_block(),
        write_text("마지막 모델 응답 원문 저장", 'baseDir & sid & "_response.txt"', "llmResponse"),
        write_text("분석 결과 저장 (result/error/retry_count)", 'baseDir & sid & "_analysis.json"', "finalJson")]))
    per = seq("한 건 처리", [
        assign(S, "nowIso", NOW_KST, "처리 시각(KST) 기록"),
        get_stt,
        parse_block,
        analyze_chain,
        assemble_block("maskedJson", "finalJson", "sttStage", "sttError", 'sid & ".wav"', "sessions.IndexOf(sid) + 1", "nowIso", "promptVersion", "sttEngine", "genaiModel"),
        if_("조립 실패?", 'assembleError <> ""', throw("결과 조립 실패", 'New System.InvalidOperationException(assembleError & " (세션: " & sid & ")")')),
        write_text("최종 결과 JSON 저장 (call_schema v1.0)", 'baseDir & sid & "_result.json"', "docJson"),
        log("완료 로그", 'sid & " 완료 — STT 오류: " & sttError & " / 모델 성공: " & isDone.ToString() & If(isDone, " / 재시도: " & attemptUsed.ToString(), "") & " / 최종 JSON " & docJson.Length.ToString() & "자"'),
    ], variables=[var(S, "nowIso"), var(S, "audioPath"), var(S, "sttJson"), var(S, "sttStage"), var(S, "sttError"), var(S, "sttResultJson"),
                  var(S, "parseError"), var(S, "parseResultJson"), var(S, "systemPrompt"), var(S, "userPrompt"),
                  var(S, "buildError"), var(S, "llmResponse"), var("x:Boolean", "callFailed", "False"), var(S, "docJson"), var(S, "assembleError"),
                  var(S, "transcriptJson")] + [v for v in MASK_VARS if 'Name="transcriptJson"' not in v] + VALIDATE_VARS[1:] + RETRY_VARS)
    body = seq("Main Sequence - 음성 → STT → 파싱 → 마스킹 → 분석 → 최종 JSON", [
        read_text("프롬프트 템플릿 읽기", "promptPath", "promptText"),
        foreach(S, "세션별 반복", "sessions", "sid", per)],
        variables=[
            var(S, "baseDir", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "genai_test") & System.IO.Path.DirectorySeparatorChar'),
            var(S, "promptPath", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "prompts", "prompt_v1_1.txt")'),
            var(S, "sttMode", '"saved"'),
            var(S, "audioDir", 'System.IO.Path.GetFullPath(System.IO.Path.Combine(System.Environment.CurrentDirectory, "..", "test"))'),
            var(S, "configPath", 'If(Not String.IsNullOrEmpty(System.Environment.GetEnvironmentVariable("CLOVA_CONFIG")), System.Environment.GetEnvironmentVariable("CLOVA_CONFIG"), System.IO.Path.GetFullPath(System.IO.Path.Combine(System.Environment.CurrentDirectory, "..", "config.json")))'),
            var("x:Int32", "maxRetry", "2"), var(S, "promptText"),
            var(S, "promptVersion", '"v1_1"'), var(S, "sttEngine", '"clova-speech"'), var(S, "genaiModel", '"gpt-6-luna"'),
            var("scg:List(x:String)", "sessions", str_list(C.SIDS))])
    return wrap(header, "Main_Step1to7", body)
