# -*- coding: utf-8 -*-
"""
UiPath 프로젝트에 넣을 XAML 4개를 만든다.  python build_xaml.py

  Step1_BuildPrompt_Test.xaml   프롬프트 조립 단계 테스트  (입력: test_data\\step1, 출력: test_data_out\\step1)
  Step2_Validate_Test.xaml      응답 검증 단계 테스트      (입력: test_data\\step2, 출력: test_data_out\\step2)
  Step3_Retry_Test.xaml         재시도 루프 테스트         (입력: test_data\\step3, 출력: test_data_out\\step3)
  Main_Step123.xaml             Main_ModelTest.xaml(옛 Main.xaml) 구조를 유지하고 Step1~3을 넣은 전체 흐름 (실제 Content Generation 호출)

Invoke Code 에 들어가는 코드는 snippets\\*.vb 파일 그대로다 (vb_check.py 가 컴파일·검증한 것과 같은 파일).
Main.xaml 은 Main_Folder 를 호출하는 시작 파일로 생성한다. 모델 호출 연결 테스트는 Main_ModelTest.xaml 이며, 이 파일에서 Content Generation 설정을 읽는다.
"""
import json
import os
import re
import sys

import common as C

SNIP = os.path.join(C.HERE, "snippets")


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
            .replace("\r", "").replace("\n", "&#xA;").replace("\t", "&#x9;"))


def code_of(name):
    with open(os.path.join(SNIP, name), encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n").rstrip("\n")


# ---------------------------------------------------------------- 액티비티 조각
def var(typ, name, default=None):
    d = ' Default="[%s]"' % esc(default) if default is not None else ""
    return '<Variable x:TypeArguments="%s"%s Name="%s" />' % (typ, d, name)


def seq(display, children, variables=()):
    v = ""
    if variables:
        v = "<Sequence.Variables>" + "".join(variables) + "</Sequence.Variables>"
    return '<Sequence DisplayName="%s">%s%s</Sequence>' % (esc(display), v, "".join(children))


def assign(typ, to, value, display="값 설정"):
    return '<Assign x:TypeArguments="%s" DisplayName="%s" To="[%s]" Value="[%s]" />' % (typ, esc(display), esc(to), esc(value))


def read_text(display, filename_expr, content_var):
    return ('<ui:ReadTextFile File="{x:Null}" Content="[%s]" DisplayName="%s" Encoding="utf-8" FileName="[%s]" />'
            % (content_var, esc(display), esc(filename_expr)))


def write_text(display, filename_expr, text_var):
    return ('<ui:WriteTextFile File="{x:Null}" Output="{x:Null}" DisplayName="%s" Encoding="utf-8" FileName="[%s]" Text="[%s]" />'
            % (esc(display), esc(filename_expr), text_var))


def make_dir(display, path_expr):
    return '<ui:CreateDirectory DisplayName="%s" Output="{x:Null}" Path="[%s]" />' % (esc(display), esc(path_expr))


def log(display, msg_expr):
    return '<ui:LogMessage DisplayName="%s" Level="Info" Message="[%s]" />' % (esc(display), esc(msg_expr))


def invoke_code(display, snippet_file, args):
    """args: [(방향 'In'|'Out', 타입, 코드 안 이름, 워크플로 변수/식)]"""
    items = []
    for d, t, key, expr in args:
        items.append('<%sArgument x:TypeArguments="%s" x:Key="%s">[%s]</%sArgument>' % (d, t, key, esc(expr), d))
    return ('<ui:InvokeCode DisplayName="%s" Language="VBNet" Code="%s"><ui:InvokeCode.Arguments>'
            '<scg:Dictionary x:TypeArguments="x:String, Argument">%s</scg:Dictionary></ui:InvokeCode.Arguments></ui:InvokeCode>'
            % (esc(display), esc(code_of(snippet_file)), "".join(items)))


def foreach(typ, display, values_expr, item, body):
    return ('<ui:ForEach x:TypeArguments="%s" CurrentIndex="{x:Null}" DisplayName="%s" Values="[%s]"><ui:ForEach.Body>'
            '<ActivityAction x:TypeArguments="%s"><ActivityAction.Argument><DelegateInArgument x:TypeArguments="%s" Name="%s" />'
            '</ActivityAction.Argument>%s</ActivityAction></ui:ForEach.Body></ui:ForEach>'
            % (typ, esc(display), esc(values_expr), typ, typ, item, body))


def if_(display, cond, then, else_=None):
    e = "<If.Else>%s</If.Else>" % else_ if else_ else ""
    return '<If Condition="[%s]" DisplayName="%s"><If.Then>%s</If.Then>%s</If>' % (esc(cond), esc(display), then, e)


def throw(display, exc_expr):
    return '<Throw DisplayName="%s" Exception="[%s]" />' % (esc(display), esc(exc_expr))


def try_catch(display, try_body, catch_body):
    return ('<TryCatch DisplayName="%s"><TryCatch.Try>%s</TryCatch.Try><TryCatch.Catches><Catch x:TypeArguments="s:Exception">'
            '<ActivityAction x:TypeArguments="s:Exception"><ActivityAction.Argument><DelegateInArgument x:TypeArguments="s:Exception" Name="exception" />'
            '</ActivityAction.Argument>%s</ActivityAction></Catch></TryCatch.Catches></TryCatch>' % (esc(display), try_body, catch_body))


def str_list(names):
    return "New System.Collections.Generic.List(Of String) From {%s}" % ", ".join('"%s"' % n for n in names)


# ---------------------------------------------------------------- 헤더
HEADER_TEST = '''<Activity mc:Ignorable="sap sap2010" x:Class="@@CLASS@@" VisualBasic.Settings="{x:Null}" xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:sap="http://schemas.microsoft.com/netfx/2009/xaml/activities/presentation" xmlns:sap2010="http://schemas.microsoft.com/netfx/2010/xaml/activities/presentation" xmlns:scg="clr-namespace:System.Collections.Generic;assembly=System.Private.CoreLib" xmlns:sco="clr-namespace:System.Collections.ObjectModel;assembly=System.Private.CoreLib" xmlns:ui="http://schemas.uipath.com/workflow/activities" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
  <TextExpression.NamespacesForImplementation>
    <sco:Collection x:TypeArguments="x:String">
      <x:String>System.Activities</x:String>
      <x:String>System.Activities.Statements</x:String>
      <x:String>System.Activities.Expressions</x:String>
      <x:String>System.Activities.Validation</x:String>
      <x:String>System.Activities.XamlIntegration</x:String>
      <x:String>Microsoft.VisualBasic</x:String>
      <x:String>Microsoft.VisualBasic.Activities</x:String>
      <x:String>System</x:String>
      <x:String>System.Collections</x:String>
      <x:String>System.Collections.Generic</x:String>
      <x:String>System.Collections.ObjectModel</x:String>
      <x:String>System.Data</x:String>
      <x:String>System.Diagnostics</x:String>
      <x:String>System.Drawing</x:String>
      <x:String>System.IO</x:String>
      <x:String>System.Linq</x:String>
      <x:String>System.Net.Mail</x:String>
      <x:String>System.Xml</x:String>
      <x:String>System.Xml.Linq</x:String>
      <x:String>UiPath.Core</x:String>
      <x:String>UiPath.Core.Activities</x:String>
      <x:String>System.Windows.Markup</x:String>
      <x:String>GlobalVariablesNamespace</x:String>
      <x:String>GlobalConstantsNamespace</x:String>
    </sco:Collection>
  </TextExpression.NamespacesForImplementation>
  <TextExpression.ReferencesForImplementation>
    <sco:Collection x:TypeArguments="AssemblyReference">
      <AssemblyReference>System.Activities</AssemblyReference>
      <AssemblyReference>Microsoft.VisualBasic</AssemblyReference>
      <AssemblyReference>System.Private.CoreLib</AssemblyReference>
      <AssemblyReference>mscorlib</AssemblyReference>
      <AssemblyReference>System.Data</AssemblyReference>
      <AssemblyReference>System</AssemblyReference>
      <AssemblyReference>System.Linq</AssemblyReference>
      <AssemblyReference>System.Data.Common</AssemblyReference>
      <AssemblyReference>System.Drawing</AssemblyReference>
      <AssemblyReference>System.Drawing.Primitives</AssemblyReference>
      <AssemblyReference>System.Drawing.Common</AssemblyReference>
      <AssemblyReference>System.Core</AssemblyReference>
      <AssemblyReference>System.Xml</AssemblyReference>
      <AssemblyReference>System.Xml.Linq</AssemblyReference>
      <AssemblyReference>PresentationFramework</AssemblyReference>
      <AssemblyReference>WindowsBase</AssemblyReference>
      <AssemblyReference>PresentationCore</AssemblyReference>
      <AssemblyReference>System.Xaml</AssemblyReference>
      <AssemblyReference>UiPath.System.Activities</AssemblyReference>
      <AssemblyReference>UiPath.UiAutomation.Activities</AssemblyReference>
      <AssemblyReference>System.Data.DataSetExtensions</AssemblyReference>
      <AssemblyReference>System.Net.Mail</AssemblyReference>
      <AssemblyReference>System.ObjectModel</AssemblyReference>
      <AssemblyReference>System.ComponentModel.TypeConverter</AssemblyReference>
    </sco:Collection>
  </TextExpression.ReferencesForImplementation>
'''


def add_refs(header):
    """Newtonsoft.Json / 정규식 어셈블리·네임스페이스를 헤더에 추가 (Invoke Code 가 사용)"""
    ns = "".join("      <x:String>%s</x:String>\n" % n for n in ("Newtonsoft.Json", "Newtonsoft.Json.Linq", "System.Text.RegularExpressions") if "<x:String>%s</x:String>" % n not in header)
    asm = "".join("      <AssemblyReference>%s</AssemblyReference>\n" % n for n in ("Newtonsoft.Json", "System.Text.RegularExpressions") if "<AssemblyReference>%s</AssemblyReference>" % n not in header)
    i = header.index("</sco:Collection>")
    header = header[:i] + ns + "    " + header[i:]
    j = header.index("</sco:Collection>", i + len(ns) + 10)
    return header[:j] + asm + "    " + header[j:]


def wrap(header, class_name, body):
    return header.replace("@@CLASS@@", class_name) + "  " + body + "\n</Activity>\n"


def save(name, text):
    p = os.path.join(C.UIPATH, name)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return p


PATHS = [
    var("x:String", "testDir", "System.IO.Path.Combine(System.Environment.CurrentDirectory, \"test_data\")"),
    var("x:String", "outDir", "System.IO.Path.Combine(System.Environment.CurrentDirectory, \"test_data_out\")"),
]
S = "x:String"


# ---------------------------------------------------------------- Step1
def step1(cases):
    inner = seq("한 건 처리", [
        read_text("프롬프트 템플릿 읽기", 'System.IO.Path.Combine(testDir, "step1", caseName, "prompt.txt")', "promptText"),
        read_text("전사본 읽기", 'System.IO.Path.Combine(testDir, "step1", caseName, "transcript.txt")', "transcriptText"),
        invoke_code("프롬프트 조립 (Invoke Code)", "build_prompt.vb", [
            ("In", S, "promptText", "promptText"), ("In", S, "transcriptText", "transcriptText"),
            ("Out", S, "systemPrompt", "systemPrompt"), ("Out", S, "userPrompt", "userPrompt"), ("Out", S, "buildError", "buildError")]),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step1", caseName)'),
        write_text("system.txt 저장", 'System.IO.Path.Combine(outDir, "step1", caseName, "system.txt")', "systemPrompt"),
        write_text("user.txt 저장", 'System.IO.Path.Combine(outDir, "step1", caseName, "user.txt")', "userPrompt"),
        write_text("error.txt 저장", 'System.IO.Path.Combine(outDir, "step1", caseName, "error.txt")', "buildError"),
        log("로그", 'caseName & " 프롬프트 조립 완료 (system " & systemPrompt.Length.ToString() & "자, user " & userPrompt.Length.ToString() & "자, 오류: " & buildError & ")"'),
    ], variables=[var(S, "promptText"), var(S, "transcriptText"), var(S, "systemPrompt"), var(S, "userPrompt"), var(S, "buildError")])
    body = seq("Step1 프롬프트 조립 테스트", [foreach(S, "케이스별 반복", "cases", "caseName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "cases", str_list(cases))])
    return wrap(add_refs(HEADER_TEST), "Step1_BuildPrompt_Test", body)


# ---------------------------------------------------------------- Step2
VALIDATE_ARGS = [("In", S, "responseText", "responseText"), ("Out", "x:Boolean", "isValid", "isValid"), ("Out", S, "errorText", "errorText"),
                 ("Out", S, "cleanedJson", "cleanedJson"), ("Out", S, "resultJson", "resultJson")]
VALIDATE_VARS = [var(S, "responseText"), var("x:Boolean", "isValid"), var(S, "errorText"), var(S, "cleanedJson"), var(S, "resultJson")]


def step2(cases):
    inner = seq("한 건 처리", [
        read_text("모델 응답 읽기", 'System.IO.Path.Combine(testDir, "step2", caseName & ".txt")', "responseText"),
        invoke_code("응답 검증 (Invoke Code)", "validate_response.vb", VALIDATE_ARGS),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step2")'),
        write_text("결과 JSON 저장", 'System.IO.Path.Combine(outDir, "step2", caseName & ".json")', "resultJson"),
        log("로그", 'caseName & " → 유효: " & isValid.ToString() & " / " & errorText'),
    ], variables=VALIDATE_VARS)
    body = seq("Step2 응답 검증 테스트", [foreach(S, "케이스별 반복", "cases", "caseName", inner)],
               variables=PATHS + [var("scg:List(x:String)", "cases", str_list(cases))])
    return wrap(add_refs(HEADER_TEST), "Step2_Validate_Test", body)


# ---------------------------------------------------------------- 재시도 루프 (Step3 공통 부분)
def finalize_block(final_var="finalJson"):
    return invoke_code("재시도 결과 정리 (Invoke Code)", "finalize_result.vb", [
        ("In", "x:Boolean", "isDone", "isDone"), ("In", S, "cleanedJson", "cleanedFinal"), ("In", S, "lastError", "lastError"),
        ("In", "x:Int32", "maxRetry", "maxRetry"), ("In", "x:Int32", "attemptUsed", "attemptUsed"), ("Out", S, "finalJson", final_var)])


def on_valid_else_error():
    return if_("검증 통과?", "isValid",
               seq("성공 처리", [assign("x:Boolean", "isDone", "True", "성공 표시"), assign(S, "cleanedFinal", "cleanedJson", "검증된 JSON 보관"),
                              assign("x:Int32", "attemptUsed", "attempt", "성공한 시도 번호")]),
               assign(S, "lastError", "errorText", "마지막 실패 사유 기록"))


RETRY_VARS = [var("x:Boolean", "isDone", "False"), var(S, "lastError", '"원인 불명"'), var("x:Int32", "attemptUsed", "0"), var(S, "cleanedFinal"), var(S, "finalJson")]


def step3(scenarios):
    attempt_body = if_("아직 성공 못 했으면 시도", "Not isDone", seq("시도", [
        read_text("시도별 응답 읽기 (모의: 실제 호출 대신 파일)", 'System.IO.Path.Combine(testDir, "step3", scName, "attempt" & (attempt + 1).ToString() & ".txt")', "responseText"),
        invoke_code("응답 검증 (Invoke Code)", "validate_response.vb", VALIDATE_ARGS),
        on_valid_else_error()]))
    inner = seq("시나리오 처리", [
        foreach("x:Int32", "시도 반복 (최초 1회 + 재시도)", "Enumerable.Range(0, maxRetry + 1)", "attempt", attempt_body),
        finalize_block(),
        make_dir("결과 폴더 만들기", 'System.IO.Path.Combine(outDir, "step3")'),
        write_text("결과 JSON 저장", 'System.IO.Path.Combine(outDir, "step3", scName & ".json")', "finalJson"),
        log("로그", 'scName & " → 성공: " & isDone.ToString() & ", 재시도 횟수: " & attemptUsed.ToString()'),
    ], variables=VALIDATE_VARS + RETRY_VARS)
    body = seq("Step3 재시도 테스트", [foreach(S, "시나리오별 반복", "scenarios", "scName", inner)],
               variables=PATHS + [var("x:Int32", "maxRetry", "2"), var("scg:List(x:String)", "scenarios", str_list(scenarios))])
    return wrap(add_refs(HEADER_TEST), "Step3_Retry_Test", body)


# ---------------------------------------------------------------- Main_Step123
def main_step123():
    with open(os.path.join(C.UIPATH, "Main_ModelTest.xaml"), encoding="utf-8") as f:
        orig = f.read()
    m = re.search(r"<isactr:ConnectorActivity .*?</isactr:ConnectorActivity>", orig, flags=re.S)
    if not m:
        raise SystemExit("현재 Main_ModelTest.xaml 에서 Content Generation(ConnectorActivity)을 찾지 못했습니다. 먼저 Studio 에서 연결을 구성하세요.")
    connector = m.group(0)
    header = orig[:orig.index("<Sequence ")]
    header = re.sub(r' x:Class="[^"]*"', ' x:Class="@@CLASS@@"', header, count=1)
    header = header.replace(' sap2010:WorkflowViewState.IdRef="ActivityBuilder_1"', "")
    if 'xmlns:s=' not in header:
        header = header.replace(' xmlns:sap=', ' xmlns:s="clr-namespace:System;assembly=System.Private.CoreLib" xmlns:sap=', 1)
    header = add_refs(header)

    call = try_catch("모델 호출 (예외도 실패로 취급)",
                     seq("호출", [connector]),
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
        read_text("전사본 읽기", 'baseDir & sid & "_transcript.txt"', "transcriptText"),
        invoke_code("프롬프트 조립 (Invoke Code)", "build_prompt.vb", [
            ("In", S, "promptText", "promptText"), ("In", S, "transcriptText", "transcriptText"),
            ("Out", S, "systemPrompt", "systemPrompt"), ("Out", S, "userPrompt", "userPrompt"), ("Out", S, "buildError", "buildError")]),
        if_("프롬프트 조립 실패?", 'buildError <> ""', throw("프롬프트 조립 실패", 'New System.InvalidOperationException(buildError & " (세션: " & sid & ")")')),
        write_text("조립한 system 프롬프트 저장 (Python 결과와 비교용)", 'baseDir & "ui_" & sid & "_system.txt"', "systemPrompt"),
        write_text("조립한 user 프롬프트 저장 (Python 결과와 비교용)", 'baseDir & "ui_" & sid & "_user.txt"', "userPrompt"),
        foreach("x:Int32", "시도 반복 (최초 1회 + 재시도)", "Enumerable.Range(0, maxRetry + 1)", "attempt", attempt_body),
        finalize_block(),
        write_text("마지막 모델 응답 원문 저장", 'baseDir & sid & "_response.txt"', "llmResponse"),
        write_text("검증 결과 저장 (result/error/retry_count)", 'baseDir & sid & "_analysis.json"', "finalJson"),
        log("완료 로그", 'sid & " 완료 — 성공: " & isDone.ToString() & ", 재시도: " & attemptUsed.ToString() & ", 응답 " & llmResponse.Length.ToString() & "자"'),
    ], variables=[var(S, "transcriptText"), var(S, "systemPrompt"), var(S, "userPrompt"), var(S, "buildError"), var(S, "llmResponse"),
                  var("x:Boolean", "callFailed", "False")] + VALIDATE_VARS[1:] + RETRY_VARS)
    body = seq("Main Sequence - GenAI (Step1~3 UiPath 변환)", [
        read_text("프롬프트 템플릿 읽기", "promptPath", "promptText"),
        foreach(S, "세션별 반복", "sessions", "sid", per)],
        variables=[
            var(S, "baseDir", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "genai_test") & System.IO.Path.DirectorySeparatorChar'),
            var(S, "promptPath", 'System.IO.Path.Combine(System.Environment.CurrentDirectory, "prompts", "prompt_v1_2.txt")'),
            var("x:Int32", "maxRetry", "2"), var(S, "promptText"),
            var("scg:List(x:String)", "sessions", str_list(C.SIDS))])
    return wrap(header, "Main_Step123", body)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import build_xaml45  # Step4·Step5 테스트와 Main_Step1to5
    import build_xaml67  # Step6·Step7 테스트와 Main_Step1to7
    import build_xaml89  # Step8 폴더 순회 (Main_Folder, Step8_Folder_Test)
    cases = json.load(open(os.path.join(C.TEST, "cases.json"), encoding="utf-8"))
    files = {
        "Step1_BuildPrompt_Test.xaml": step1(cases["step1"]),
        "Step2_Validate_Test.xaml": step2(cases["step2"]),
        "Step3_Retry_Test.xaml": step3(cases["step3"]),
        "Main_Step123.xaml": main_step123(),
        "Step4_Mask_Test.xaml": build_xaml45.step4(cases["step4"]),
        "Step5_Assemble_Test.xaml": build_xaml45.step5(cases["step5"]),
        "Main_Step1to5.xaml": build_xaml45.main_step1to5(),
        "Step6_SttCall_Test.xaml": build_xaml67.step6(cases["step6"]),
        "Step7_Parse_Test.xaml": build_xaml67.step7(cases["step7"]),
        "Main_Step1to7.xaml": build_xaml67.main_step1to7(),
        "Step8_Folder_Test.xaml": build_xaml89.folder_flow(True),
        "Main_Folder.xaml": build_xaml89.folder_flow(False),
        "Run_All.xaml": build_xaml45.run_all(),
        "Main.xaml": build_xaml45.main_entry(),  # 시작 파일: Main_Folder 호출 (기존 연결 테스트는 Main_ModelTest.xaml)
    }
    import xml.etree.ElementTree as ET
    for name, text in files.items():
        ET.fromstring(text)  # XML 형식 확인
        print("생성:", save(name, text), "(%d자)" % len(text))


if __name__ == "__main__":
    main()
