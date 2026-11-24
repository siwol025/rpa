import type { CallDetail } from '../api/types'

// design/dashboard-mockup-v0.2.html의 예시 상담을 변환한 mock 데이터 (실제 고객 정보 아님)
export const MOCK_CALLS: CallDetail[] = [
  {
    "id": 1,
    "source_type": "DRIVE",
    "original_name": "20261110_091200_김상담_A산업.mp3",
    "duration_sec": 214,
    "agent_name": "김상담",
    "client_company": "A산업",
    "call_datetime": "2026-11-10T09:12:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-10T09:25:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "AGENT",
          "start": 0,
          "end": 4,
          "text": "안녕하세요, 고객센터 김상담입니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 5,
          "end": 11,
          "text": "다음 주 출장인데 법인카드가 해외에서 막혀 있어요."
        },
        {
          "speaker": "AGENT",
          "start": 12,
          "end": 17,
          "text": "확인을 위해 등록된 연락처를 말씀해 주세요."
        },
        {
          "speaker": "CUSTOMER",
          "start": 18,
          "end": 22,
          "text": "010-****-5821이에요."
        },
        {
          "speaker": "AGENT",
          "start": 23,
          "end": 31,
          "text": "해제했습니다. 21일 이후에는 다시 차단되도록 설정해 드렸어요."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.93,
      "question_summary": "출장 중 사용할 법인카드의 해외 결제 차단 해제 방법을 문의함.",
      "action_summary": "본인 확인 후 차단을 해제하고, 11월 21일 이후 다시 차단되도록 설정함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "A산업",
        "products": [
          "법인카드"
        ],
        "dates": [
          "11월 21일"
        ],
        "keywords": [
          "해외 결제",
          "차단 해제"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:20:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:21:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:22:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:23:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:24:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T09:25:00+09:00"
      }
    ]
  },
  {
    "id": 2,
    "source_type": "DRIVE",
    "original_name": "20261110_144000_박상담_B물류.mp3",
    "duration_sec": 356,
    "agent_name": "박상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-10T14:40:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-10T14:53:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 7,
          "text": "아침에 이체했는데 아직 못 받았대요. 거래처라 급합니다."
        },
        {
          "speaker": "AGENT",
          "start": 8,
          "end": 14,
          "text": "불편을 드려 죄송합니다. 이체 내역을 확인하겠습니다."
        },
        {
          "speaker": "AGENT",
          "start": 15,
          "end": 21,
          "text": "받는 은행의 전산 점검으로 처리가 늦어지고 있습니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 22,
          "end": 25,
          "text": "입금되면 꼭 알려 주세요."
        }
      ]
    },
    "analysis": {
      "category": "COMPLAINT",
      "confidence": 0.91,
      "question_summary": "오전에 보낸 타행 이체가 2시간 넘게 입금되지 않았다고 항의함.",
      "action_summary": "수취 은행 전산 점검으로 지연 중임을 안내하고, 입금이 확인되면 다시 연락하기로 함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "B물류",
        "products": [
          "타행 이체"
        ],
        "dates": [
          "11월 10일"
        ],
        "keywords": [
          "입금 지연",
          "전산 점검"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:48:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:49:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:50:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:51:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:52:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-10T14:53:00+09:00"
      }
    ]
  },
  {
    "id": 3,
    "source_type": "WEB",
    "original_name": "20261111_100500_이상담_C테크.mp3",
    "duration_sec": 402,
    "agent_name": "이상담",
    "client_company": "C테크",
    "call_datetime": "2026-11-11T10:05:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-11T10:18:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 6,
          "text": "운전자금 대출을 받으려는데 서류가 뭐가 필요한가요?"
        },
        {
          "speaker": "AGENT",
          "start": 7,
          "end": 13,
          "text": "사업자등록증과 최근 2년 재무제표가 필요합니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 14,
          "end": 18,
          "text": "목록을 메일로 받을 수 있을까요?"
        },
        {
          "speaker": "AGENT",
          "start": 19,
          "end": 23,
          "text": "네, 바로 보내 드리겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.95,
      "question_summary": "운전자금 대출을 신청할 때 필요한 서류를 문의함.",
      "action_summary": "필요 서류 목록을 안내하고 담당자 이메일로 보냄.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "C테크",
        "products": [
          "운전자금 대출"
        ],
        "dates": [],
        "keywords": [
          "필요 서류"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:13:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:14:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:15:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:16:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:17:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T10:18:00+09:00"
      }
    ]
  },
  {
    "id": 4,
    "source_type": "DRIVE",
    "original_name": "20261111_152000_김상담_D식품.mp3",
    "duration_sec": 488,
    "agent_name": "김상담",
    "client_company": "D식품",
    "call_datetime": "2026-11-11T15:20:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-11T15:33:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "OTP를 처음 등록하는데 어디서 하나요?"
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 12,
          "text": "인증센터 메뉴에서 OTP 등록을 선택해 주세요."
        },
        {
          "speaker": "CUSTOMER",
          "start": 13,
          "end": 16,
          "text": "번호를 넣으라고 나와요."
        },
        {
          "speaker": "AGENT",
          "start": 17,
          "end": 22,
          "text": "기기 뒷면 번호를 넣으시면 등록이 끝납니다."
        }
      ]
    },
    "analysis": {
      "category": "EDUCATION",
      "confidence": 0.88,
      "question_summary": "새로 온 직원이 기업뱅킹 OTP 등록 방법을 안내해 달라고 요청함.",
      "action_summary": "등록 화면을 함께 보며 단계별로 안내하고 등록 완료를 확인함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "D식품",
        "products": [
          "기업뱅킹",
          "OTP"
        ],
        "dates": [],
        "keywords": [
          "OTP 등록",
          "사용법"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:28:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:29:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:30:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:31:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:32:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-11T15:33:00+09:00"
      }
    ]
  },
  {
    "id": 5,
    "source_type": "DRIVE",
    "original_name": "20261112_095000_박상담_E건설.mp3",
    "duration_sec": 233,
    "agent_name": "박상담",
    "client_company": "E건설",
    "call_datetime": "2026-11-12T09:50:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-12T10:03:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "대금이 커서 이체 한도를 올려야 해요."
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 12,
          "text": "신청서와 법인 인감증명서를 제출하시면 됩니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 13,
          "end": 15,
          "text": "네, 알겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.94,
      "question_summary": "공사 대금 지급을 위해 1일 이체 한도를 올리는 방법을 문의함.",
      "action_summary": "한도 상향에 필요한 서류와 신청 절차를 안내함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "E건설",
        "products": [
          "이체 한도"
        ],
        "dates": [],
        "keywords": [
          "한도 상향"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T09:58:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T09:59:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T10:00:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T10:01:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T10:02:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T10:03:00+09:00"
      }
    ]
  },
  {
    "id": 6,
    "source_type": "DRIVE",
    "original_name": "20261112_133000_이상담_A산업.mp3",
    "duration_sec": 142,
    "agent_name": "이상담",
    "client_company": "A산업",
    "call_datetime": "2026-11-12T13:30:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-12T13:43:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "이체 결과를 한 번에 받을 수는 없나요?"
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 13,
          "text": "지금은 건별로만 가능합니다. 개선 의견으로 접수하겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "SUGGESTION",
      "confidence": 0.86,
      "question_summary": "여러 건의 이체 결과를 한 번에 내려받는 기능을 요청함.",
      "action_summary": "현재는 건별로 받을 수 있음을 안내하고 개선 의견으로 접수함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "A산업",
        "products": [
          "기업뱅킹"
        ],
        "dates": [],
        "keywords": [
          "이체 결과",
          "일괄 다운로드"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:38:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:39:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:40:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:41:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:42:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-12T13:43:00+09:00"
      }
    ]
  },
  {
    "id": 7,
    "source_type": "DRIVE",
    "original_name": "20261113_101800_김상담_B물류.mp3",
    "duration_sec": 512,
    "agent_name": "김상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-13T10:18:00+09:00",
    "metadata_incomplete": false,
    "status": "NEEDS_REVIEW",
    "status_changed_at": "2026-11-13T10:31:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 3,
          "text": "로그인이 사흘째 안 돼요."
        },
        {
          "speaker": "AGENT",
          "start": 4,
          "end": 8,
          "text": "프로그램을 다시 설치해 보셨을까요?"
        },
        {
          "speaker": "CUSTOMER",
          "start": 9,
          "end": 12,
          "text": "두 번이나 했는데 똑같아요."
        },
        {
          "speaker": "AGENT",
          "start": 13,
          "end": 18,
          "text": "전산 담당에 접수하고 다시 연락드리겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "COMPLAINT",
      "confidence": 0.55,
      "question_summary": "기업뱅킹 로그인 오류가 사흘째 반복되어 이체를 하지 못한다고 함.",
      "action_summary": "재설치를 안내했으나 해결되지 않아 전산 담당에 접수함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "B물류",
        "products": [
          "기업뱅킹"
        ],
        "dates": [],
        "keywords": [
          "로그인 오류",
          "전산 접수"
        ]
      },
      "needs_review": true
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:26:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:27:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:28:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:29:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:30:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T10:31:00+09:00"
      }
    ]
  },
  {
    "id": 8,
    "source_type": "DRIVE",
    "original_name": "20261113_160200_박상담_C테크.mp3",
    "duration_sec": 265,
    "agent_name": "박상담",
    "client_company": "C테크",
    "call_datetime": "2026-11-13T16:02:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-13T16:15:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 3,
          "text": "법인카드를 잃어버렸어요."
        },
        {
          "speaker": "AGENT",
          "start": 4,
          "end": 12,
          "text": "카드 번호 끝자리가 ****-****-****-3391 맞으실까요?"
        },
        {
          "speaker": "CUSTOMER",
          "start": 13,
          "end": 15,
          "text": "네, 맞아요."
        },
        {
          "speaker": "AGENT",
          "start": 16,
          "end": 22,
          "text": "사용 정지했습니다. 재발급도 신청해 드렸어요."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.96,
      "question_summary": "법인카드 분실 신고와 재발급 절차를 문의함.",
      "action_summary": "사용 정지 처리 후 재발급을 신청함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "C테크",
        "products": [
          "법인카드"
        ],
        "dates": [],
        "keywords": [
          "분실 신고",
          "재발급"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:10:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:11:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:12:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:13:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:14:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-13T16:15:00+09:00"
      }
    ]
  },
  {
    "id": 9,
    "source_type": "DRIVE",
    "original_name": "20261116_105500_이상담_D식품.mp3",
    "duration_sec": 604,
    "agent_name": "이상담",
    "client_company": "D식품",
    "call_datetime": "2026-11-16T10:55:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-16T11:08:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "잘못 보낸 돈을 2주째 못 돌려받고 있어요."
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 11,
          "text": "죄송합니다. 진행 상황을 확인하겠습니다."
        },
        {
          "speaker": "AGENT",
          "start": 12,
          "end": 18,
          "text": "받는 분과 연락이 닿지 않아 늦어지고 있습니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 19,
          "end": 22,
          "text": "진행되면 꼭 알려 주세요."
        }
      ]
    },
    "analysis": {
      "category": "COMPLAINT",
      "confidence": 0.92,
      "question_summary": "2주 전 잘못 보낸 송금의 반환이 늦어진다고 항의함.",
      "action_summary": "수취인과 연락이 되지 않아 지연 중임을 설명하고 진행 상황을 다시 알리기로 함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "D식품",
        "products": [
          "송금"
        ],
        "dates": [],
        "keywords": [
          "착오송금",
          "반환 지연"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:03:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:04:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:05:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:06:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:07:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T11:08:00+09:00"
      }
    ]
  },
  {
    "id": 10,
    "source_type": "DRIVE",
    "original_name": "20261116_143000_김상담_E건설.mp3",
    "duration_sec": 176,
    "agent_name": "김상담",
    "client_company": "E건설",
    "call_datetime": "2026-11-16T14:30:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-16T14:43:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 6,
          "text": "이체 알림을 여러 명이 받을 수 있으면 좋겠어요."
        },
        {
          "speaker": "AGENT",
          "start": 7,
          "end": 13,
          "text": "지금은 한 분만 등록됩니다. 의견으로 접수하겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "SUGGESTION",
      "confidence": 0.84,
      "question_summary": "이체 알림을 담당자 여러 명이 함께 받게 해 달라고 건의함.",
      "action_summary": "현재는 1명만 등록할 수 있음을 안내하고 개선 의견으로 접수함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "E건설",
        "products": [
          "이체 알림"
        ],
        "dates": [],
        "keywords": [
          "알림",
          "담당자 추가"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:38:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:39:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:40:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:41:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:42:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-16T14:43:00+09:00"
      }
    ]
  },
  {
    "id": 11,
    "source_type": "DRIVE",
    "original_name": "20261117_094500_박상담_A산업.mp3",
    "duration_sec": 395,
    "agent_name": "박상담",
    "client_company": "A산업",
    "call_datetime": "2026-11-17T09:45:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-17T09:58:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "25일 급여이체 파일을 처음 올려 봐요."
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 13,
          "text": "양식을 내려받아 작성한 뒤 일괄이체 메뉴에서 올려 주세요."
        },
        {
          "speaker": "CUSTOMER",
          "start": 14,
          "end": 16,
          "text": "등록됐다고 나와요."
        }
      ]
    },
    "analysis": {
      "category": "EDUCATION",
      "confidence": 0.9,
      "question_summary": "급여이체 파일을 올리는 방법을 안내해 달라고 요청함.",
      "action_summary": "파일 양식과 업로드 순서를 안내하고 정상 등록을 확인함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "A산업",
        "products": [
          "급여이체"
        ],
        "dates": [
          "11월 25일"
        ],
        "keywords": [
          "파일 업로드",
          "급여이체"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:53:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:54:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:55:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:56:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:57:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T09:58:00+09:00"
      }
    ]
  },
  {
    "id": 12,
    "source_type": "DRIVE",
    "original_name": "20261117_160500_이상담_B물류.mp3",
    "duration_sec": 468,
    "agent_name": "이상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-17T16:05:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-17T16:18:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "같은 금액이 두 번 결제됐어요."
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 9,
          "text": "확인해 보니 중복 승인이 맞습니다."
        },
        {
          "speaker": "AGENT",
          "start": 10,
          "end": 14,
          "text": "가맹점에 바로 취소를 요청하겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "COMPLAINT",
      "confidence": 0.93,
      "question_summary": "법인카드가 같은 금액으로 두 번 결제되었다고 함.",
      "action_summary": "중복 승인을 확인하고 가맹점에 취소를 요청함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "B물류",
        "products": [
          "법인카드"
        ],
        "dates": [
          "11월 17일"
        ],
        "keywords": [
          "이중 결제",
          "승인 취소"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:13:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:14:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:15:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:16:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:17:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-17T16:18:00+09:00"
      }
    ]
  },
  {
    "id": 13,
    "source_type": "DRIVE",
    "original_name": "20261118_101000_김상담_C테크.mp3",
    "duration_sec": 188,
    "agent_name": "김상담",
    "client_company": "C테크",
    "call_datetime": "2026-11-18T10:10:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-18T10:23:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "상환일을 25일로 바꾸고 싶어요."
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 8,
          "text": "네, 변경해 드렸습니다."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.95,
      "question_summary": "대출 상환일을 15일에서 25일로 바꿀 수 있는지 문의함.",
      "action_summary": "상환일을 25일로 변경함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "C테크",
        "products": [
          "대출"
        ],
        "dates": [
          "매월 25일"
        ],
        "keywords": [
          "상환일 변경"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:18:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:19:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:20:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:21:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:22:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T10:23:00+09:00"
      }
    ]
  },
  {
    "id": 14,
    "source_type": "DRIVE",
    "original_name": "20261118_133500_박상담_D식품.mp3",
    "duration_sec": 64,
    "agent_name": "박상담",
    "client_company": "D식품",
    "call_datetime": "2026-11-18T13:35:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-18T13:48:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "대출 상담을 눌렀는데 카드 쪽으로 왔네요."
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 11,
          "text": "죄송합니다. 담당 부서로 연결하겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "ETC",
      "confidence": 0.89,
      "question_summary": "다른 부서로 잘못 연결되었다고 함.",
      "action_summary": "담당 부서로 연결함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "D식품",
        "products": [],
        "dates": [],
        "keywords": [
          "부서 연결"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:43:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:44:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:45:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:46:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:47:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-18T13:48:00+09:00"
      }
    ]
  },
  {
    "id": 15,
    "source_type": "DRIVE",
    "original_name": "20261119_092500_이상담_E건설.mp3",
    "duration_sec": 447,
    "agent_name": "이상담",
    "client_company": "E건설",
    "call_datetime": "2026-11-19T09:25:00+09:00",
    "metadata_incomplete": false,
    "status": "NEEDS_REVIEW",
    "status_changed_at": "2026-11-19T09:38:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "심사 결과를 일주일째 못 받았어요."
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 10,
          "text": "서류 추가 확인 때문에 늦어지고 있습니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 11,
          "end": 14,
          "text": "미리 알려 주셨어야죠."
        },
        {
          "speaker": "AGENT",
          "start": 15,
          "end": 20,
          "text": "죄송합니다. 오늘 오후에 연락드리겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "COMPLAINT",
      "confidence": 0.62,
      "question_summary": "대출 심사 결과를 일주일째 받지 못했다고 함.",
      "action_summary": "서류 추가 확인으로 지연 중임을 안내하고 당일 오후에 연락하기로 함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "E건설",
        "products": [
          "대출"
        ],
        "dates": [
          "11월 19일"
        ],
        "keywords": [
          "심사 지연"
        ]
      },
      "needs_review": true
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:33:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:34:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:35:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:36:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:37:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T09:38:00+09:00"
      }
    ]
  },
  {
    "id": 16,
    "source_type": "DRIVE",
    "original_name": "20261119_141500_김상담_A산업.mp3",
    "duration_sec": 356,
    "agent_name": "김상담",
    "client_company": "A산업",
    "call_datetime": "2026-11-19T14:15:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-19T14:28:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "지연이체는 어떻게 쓰는 건가요?"
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 12,
          "text": "이체하고 몇 시간 뒤에 입금되어 그사이 취소하실 수 있습니다."
        },
        {
          "speaker": "CUSTOMER",
          "start": 13,
          "end": 15,
          "text": "신청해 주세요."
        }
      ]
    },
    "analysis": {
      "category": "EDUCATION",
      "confidence": 0.87,
      "question_summary": "지연이체 서비스의 사용 방법을 안내해 달라고 요청함.",
      "action_summary": "서비스 내용과 취소 방법을 설명하고 신청을 도움.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "A산업",
        "products": [
          "지연이체"
        ],
        "dates": [],
        "keywords": [
          "지연이체",
          "사용법"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:23:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:24:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:25:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:26:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:27:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T14:28:00+09:00"
      }
    ]
  },
  {
    "id": 17,
    "source_type": "WEB",
    "original_name": "20261120_090500_박상담_B물류.mp3",
    "duration_sec": 264,
    "agent_name": "박상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-20T09:05:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-20T09:18:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "해외 송금 수수료가 얼마인가요?"
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 11,
          "text": "송금 금액에 따라 달라서 구간별로 안내해 드릴게요."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.94,
      "question_summary": "해외 송금 수수료를 문의함.",
      "action_summary": "건당 수수료와 추가 비용을 안내함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "B물류",
        "products": [
          "해외 송금"
        ],
        "dates": [],
        "keywords": [
          "수수료"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:13:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:14:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:15:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:16:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:17:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T09:18:00+09:00"
      }
    ]
  },
  {
    "id": 18,
    "source_type": "DRIVE",
    "original_name": "20261120_131000_이상담_C테크.mp3",
    "duration_sec": 95,
    "agent_name": "이상담",
    "client_company": "C테크",
    "call_datetime": "2026-11-20T13:10:00+09:00",
    "metadata_incomplete": false,
    "status": "STORED",
    "status_changed_at": "2026-11-20T13:23:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 3,
          "text": "지점이 몇 시까지 하나요?"
        },
        {
          "speaker": "AGENT",
          "start": 4,
          "end": 7,
          "text": "오후 4시까지 운영합니다."
        }
      ]
    },
    "analysis": {
      "category": "ETC",
      "confidence": 0.9,
      "question_summary": "지점 영업시간을 문의함.",
      "action_summary": "가까운 지점의 영업시간을 안내함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "C테크",
        "products": [],
        "dates": [],
        "keywords": [
          "영업시간"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:18:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:19:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:20:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:21:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:22:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-20T13:23:00+09:00"
      }
    ]
  },
  {
    "id": 19,
    "source_type": "DRIVE",
    "original_name": "20261123_103000_D식품.mp3",
    "duration_sec": 151,
    "agent_name": null,
    "client_company": "D식품",
    "call_datetime": "2026-11-23T10:30:00+09:00",
    "metadata_incomplete": true,
    "status": "STORED",
    "status_changed_at": "2026-11-23T10:43:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 3,
          "text": "잔액증명서를 떼고 싶어요."
        },
        {
          "speaker": "AGENT",
          "start": 4,
          "end": 9,
          "text": "증명서 메뉴에서 바로 발급하실 수 있습니다."
        }
      ]
    },
    "analysis": {
      "category": "INQUIRY",
      "confidence": 0.92,
      "question_summary": "잔액증명서 발급 방법을 문의함.",
      "action_summary": "기업뱅킹에서 발급하는 순서를 안내함.",
      "follow_up_required": false,
      "action_status": "DONE",
      "entities": {
        "client_company": "D식품",
        "products": [
          "잔액증명서"
        ],
        "dates": [],
        "keywords": [
          "증명서 발급"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:38:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:39:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:40:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:41:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:42:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T10:43:00+09:00"
      }
    ]
  },
  {
    "id": 20,
    "source_type": "WEB",
    "original_name": "녹음_0042.wav",
    "duration_sec": 198,
    "agent_name": null,
    "client_company": null,
    "call_datetime": null,
    "metadata_incomplete": true,
    "status": "STORED",
    "status_changed_at": "2026-11-23T11:25:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 5,
          "text": "증명서를 영문으로 받을 수 있으면 좋겠어요."
        },
        {
          "speaker": "AGENT",
          "start": 6,
          "end": 10,
          "text": "개선 의견으로 접수하겠습니다."
        }
      ]
    },
    "analysis": {
      "category": "SUGGESTION",
      "confidence": 0.83,
      "question_summary": "증명서를 영문으로도 발급해 달라고 건의함.",
      "action_summary": "개선 의견으로 접수함.",
      "follow_up_required": true,
      "action_status": "OPEN",
      "entities": {
        "client_company": "",
        "products": [
          "증명서"
        ],
        "dates": [],
        "keywords": [
          "영문 증명서"
        ]
      },
      "needs_review": false
    },
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:20:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:21:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:22:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:23:00+09:00"
      },
      {
        "step": "STORE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:24:00+09:00"
      },
      {
        "step": "EXCEL",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T11:25:00+09:00"
      }
    ]
  },
  {
    "id": 21,
    "source_type": "DRIVE",
    "original_name": "20261123_143000_김상담_A산업.mp3",
    "duration_sec": 41,
    "agent_name": "김상담",
    "client_company": "A산업",
    "call_datetime": "2026-11-23T14:30:00+09:00",
    "metadata_incomplete": false,
    "status": "FAILED",
    "status_changed_at": "2026-11-23T14:40:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": null,
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T14:38:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T14:39:00+09:00"
      },
      {
        "step": "STT",
        "status": "FAIL",
        "message": "음질이 낮아 전사하지 못했습니다.",
        "created_at": "2026-11-23T14:40:00+09:00"
      }
    ]
  },
  {
    "id": 22,
    "source_type": "DRIVE",
    "original_name": "20261123_162000_박상담_E건설.mp3",
    "duration_sec": 237,
    "agent_name": "박상담",
    "client_company": "E건설",
    "call_datetime": "2026-11-23T16:20:00+09:00",
    "metadata_incomplete": false,
    "status": "FAILED",
    "status_changed_at": "2026-11-23T16:31:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 3,
          "text": "보증서 발급이 언제 되나요?"
        },
        {
          "speaker": "AGENT",
          "start": 4,
          "end": 8,
          "text": "접수 내역을 확인해 보겠습니다."
        }
      ]
    },
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T16:28:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T16:29:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-23T16:30:00+09:00"
      },
      {
        "step": "GENAI",
        "status": "FAIL",
        "message": "분석 결과가 정해진 형식과 달랐습니다.",
        "created_at": "2026-11-23T16:31:00+09:00"
      }
    ]
  },
  {
    "id": 23,
    "source_type": "DRIVE",
    "original_name": "20261124_084000_이상담_B물류.mp3",
    "duration_sec": 182,
    "agent_name": "이상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-24T08:40:00+09:00",
    "metadata_incomplete": false,
    "status": "QUEUED",
    "status_changed_at": "2026-11-24T08:45:00+09:00",
    "retry_count": 0,
    "is_stale": true,
    "transcript": null,
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T08:48:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T08:49:00+09:00"
      }
    ]
  },
  {
    "id": 24,
    "source_type": "DRIVE",
    "original_name": "20261124_093500_김상담_C테크.mp3",
    "duration_sec": 205,
    "agent_name": "김상담",
    "client_company": "C테크",
    "call_datetime": "2026-11-24T09:35:00+09:00",
    "metadata_incomplete": false,
    "status": "STT_DONE",
    "status_changed_at": "2026-11-24T09:52:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": {
      "segments": [
        {
          "speaker": "CUSTOMER",
          "start": 0,
          "end": 4,
          "text": "법인카드 한도를 올리고 싶어요."
        },
        {
          "speaker": "AGENT",
          "start": 5,
          "end": 9,
          "text": "신청 방법을 안내해 드리겠습니다."
        }
      ]
    },
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:43:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:44:00+09:00"
      },
      {
        "step": "STT",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:45:00+09:00"
      }
    ]
  },
  {
    "id": 25,
    "source_type": "WEB",
    "original_name": "20261124_095000_박상담_D식품.mp3",
    "duration_sec": 120,
    "agent_name": "박상담",
    "client_company": "D식품",
    "call_datetime": "2026-11-24T09:50:00+09:00",
    "metadata_incomplete": false,
    "status": "REGISTERED",
    "status_changed_at": "2026-11-24T09:55:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": null,
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:58:00+09:00"
      }
    ]
  },
  {
    "id": 26,
    "source_type": "DRIVE",
    "original_name": "20261124_092000_이상담_E건설.mp3",
    "duration_sec": 301,
    "agent_name": "이상담",
    "client_company": "E건설",
    "call_datetime": "2026-11-24T09:20:00+09:00",
    "metadata_incomplete": false,
    "status": "QUEUED",
    "status_changed_at": "2026-11-24T09:45:00+09:00",
    "retry_count": 0,
    "is_stale": false,
    "transcript": null,
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:28:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-24T09:29:00+09:00"
      }
    ]
  },
  {
    "id": 27,
    "source_type": "DRIVE",
    "original_name": "20261119_171000_김상담_B물류.mp3",
    "duration_sec": 143,
    "agent_name": "김상담",
    "client_company": "B물류",
    "call_datetime": "2026-11-19T17:10:00+09:00",
    "metadata_incomplete": false,
    "status": "RETRY_REQUESTED",
    "status_changed_at": "2026-11-24T09:10:00+09:00",
    "retry_count": 1,
    "is_stale": true,
    "transcript": null,
    "analysis": null,
    "processing_log": [
      {
        "step": "REGISTER",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T17:18:00+09:00"
      },
      {
        "step": "QUEUE",
        "status": "SUCCESS",
        "message": null,
        "created_at": "2026-11-19T17:19:00+09:00"
      },
      {
        "step": "STT",
        "status": "FAIL",
        "message": "전사 요청 시간이 초과되었습니다.",
        "created_at": "2026-11-19T17:20:00+09:00"
      },
      {
        "step": "RETRY",
        "status": "RETRY",
        "message": "재처리를 요청했습니다.",
        "created_at": "2026-11-24T09:10:00+09:00"
      }
    ]
  }
]
