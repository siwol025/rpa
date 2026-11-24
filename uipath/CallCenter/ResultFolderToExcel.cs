using System;
using UiPath.CodedWorkflows;

namespace CallCenter
{
    /// <summary>
    /// [1단계] 결과 JSON 폴더 → 엑셀 보고서.
    /// Studio에서 이 파일을 우클릭 → "Run File" 로 단독 실행할 수 있다.
    /// 실제 로직은 Pipeline 클래스에 있다(UiPath 의존성 없음).
    /// </summary>
    public class ResultFolderToExcel : CodedWorkflowBase
    {
        /// <param name="configPath">Config.xlsx 경로. 비우면 프로젝트의 Data\Config.xlsx를 사용.</param>
        /// <returns>처리 결과 요약 문자열</returns>
        [Workflow]
        public string Execute(string configPath = "")
        {
            var pipeline = new Pipeline(delegate (string level, string message)
            {
                Log("[" + level + "] " + message);
            });
            RunResult result = pipeline.Run(configPath, null);
            return result.Summary();
        }
    }
}
