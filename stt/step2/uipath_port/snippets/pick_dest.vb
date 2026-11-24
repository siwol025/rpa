' Step8: 대상 폴더에서 겹치지 않는 파일 경로 정하기  (Python: run_folder.unique_dest)
' In : destDir(String) 대상 폴더, fileName(String) 원하는 파일 이름
' Out: destPath(String) destDir 에 같은 이름이 없으면 그대로, 있으면 stem_1.ext, stem_2.ext ... (같은 이름의 폴더도 충돌로 본다)
Dim pickStem As String = System.IO.Path.GetFileNameWithoutExtension(fileName)
Dim pickExt As String = System.IO.Path.GetExtension(fileName)
destPath = System.IO.Path.Combine(destDir, fileName)
If System.IO.File.Exists(destPath) OrElse System.IO.Directory.Exists(destPath) Then
    Dim pickN As Integer = 1
    Do While System.IO.File.Exists(System.IO.Path.Combine(destDir, pickStem & "_" & pickN.ToString() & pickExt)) OrElse System.IO.Directory.Exists(System.IO.Path.Combine(destDir, pickStem & "_" & pickN.ToString() & pickExt))
        pickN = pickN + 1
    Loop
    destPath = System.IO.Path.Combine(destDir, pickStem & "_" & pickN.ToString() & pickExt)
End If
