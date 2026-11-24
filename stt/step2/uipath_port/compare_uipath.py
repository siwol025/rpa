# -*- coding: utf-8 -*-
"""
Studio 에서 실행한 결과를 Python 정답과 비교한다.

  python compare_uipath.py --step 1        # Step1_BuildPrompt_Test.xaml 실행 후
  python compare_uipath.py --step 2        # Step2_Validate_Test.xaml 실행 후
  python compare_uipath.py --step 3        # Step3_Retry_Test.xaml 실행 후
  python compare_uipath.py --step main     # Main_Step123.xaml 실행 후 (실제 모델 호출 결과)
  python compare_uipath.py --step 4        # Step4_Mask_Test.xaml 실행 후
  python compare_uipath.py --step 5        # Step5_Assemble_Test.xaml 실행 후
  python compare_uipath.py --step main5    # Main_Step1to5.xaml 실행 후 (실제 모델 호출, 최종 JSON까지)
  python compare_uipath.py --step 6        # Step6_SttCall_Test.xaml 실행 후 (fake_clova.py 가 떠 있어야 함)
  python compare_uipath.py --step 7        # Step7_Parse_Test.xaml 실행 후
  python compare_uipath.py --step main7    # Main_Step1to7.xaml 실행 후 (저장된 STT 응답 + 실제 모델 호출)
  python compare_uipath.py --step 8        # Step8_Folder_Test.xaml 실행 후 (fake_clova.py 가 떠 있어야 함, --raw-high 포함)
  python compare_uipath.py --step all      # 1~8 한꺼번에

--actual 으로 결과 폴더를 바꿀 수 있다 (기본: UiPath 프로젝트의 test_data_out).
종료 코드: 0 = 모두 일치, 1 = 불일치 있음, 2 = 결과 파일 없음.
"""
import argparse
import os
import sys

import common as C


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["1", "2", "3", "4", "5", "6", "7", "8", "all", "main", "main5", "main7"])
    ap.add_argument("--actual", default=os.path.join(C.UIPATH, "test_data_out"))
    a = ap.parse_args()
    bad = 0
    if a.step in ("1", "all"):
        bad += C.report("Step1 프롬프트 조립 (UiPath vs Python)", C.compare_step1(a.actual))
    if a.step in ("2", "all"):
        bad += C.report("Step2 응답 검증 (UiPath vs Python)", C.compare_step2(a.actual))
    if a.step in ("3", "all"):
        bad += C.report("Step3 재시도 (UiPath vs Python)", C.compare_step3(a.actual))
    if a.step in ("4", "all"):
        bad += C.report("Step4 마스킹 (UiPath vs Python)", C.compare_step4(a.actual))
    if a.step in ("5", "all"):
        bad += C.report("Step5 최종 JSON 조립 (UiPath vs Python)", C.compare_step5(a.actual))
    if a.step in ("6", "all"):
        bad += C.report("Step6 STT 호출 (UiPath vs Python, fake_clova.py 요청 기록 포함)", C.compare_step6(a.actual))
    if a.step in ("7", "all"):
        bad += C.report("Step7 STT 응답 파싱 (UiPath vs Python)", C.compare_step7(a.actual))
    if a.step in ("8", "all"):
        bad += C.report("Step8 폴더 순회·파일 이동 (UiPath vs Python 기준 구현)", C.compare_step8(os.path.join(C.UIPATH, "test_data_run", "step8")))
    if a.step == "main7":
        bad += C.report("Main_Step1to7 실제 실행 (UiPath vs Python)", C.compare_main5(os.path.join(C.UIPATH, "genai_test")))
    if a.step == "main5":
        bad += C.report("Main_Step1to5 실제 실행 (UiPath vs Python)", C.compare_main5(os.path.join(C.UIPATH, "genai_test")))
    if a.step == "main":
        bad += C.report("Main_Step123 실제 실행 (UiPath vs Python)", C.compare_main(os.path.join(C.UIPATH, "genai_test")))
    print("\n결과: " + ("모두 일치" if not bad else "불일치 %d건" % bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
