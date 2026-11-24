' (Step8 테스트 전용) 실행용 폴더를 깨끗하게 다시 만든다: runRoot 를 지우고 srcRoot 의 내용(하위 폴더 포함)을 복사한다.
' In : srcRoot(String) 원본 입력 묶음, runRoot(String) 실행 폴더
' Out: resetError(String; 성공이면 "")
resetError = ""
Try
    If System.IO.Directory.Exists(runRoot) Then System.IO.Directory.Delete(runRoot, True)
    System.IO.Directory.CreateDirectory(runRoot)
    For Each srcFile As String In System.IO.Directory.GetFiles(srcRoot, "*", System.IO.SearchOption.AllDirectories)
        Dim rel As String = srcFile.Substring(srcRoot.TrimEnd(System.IO.Path.DirectorySeparatorChar).Length + 1)
        Dim target As String = System.IO.Path.Combine(runRoot, rel)
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(target))
        System.IO.File.Copy(srcFile, target, True)
    Next
Catch ex As System.Exception
    resetError = "폴더 초기화 실패(" & ex.GetType().Name & ")"
End Try
