' Step8: 파일 이동 (이름이 겹치면 번호를 붙임)  (Python: run_folder.move_unique)
' In : srcPath(String) 옮길 파일, destDir(String) 대상 폴더(없으면 만든다)
' Out: movedPath(String) 이동 후 경로 (실패하면 ""), moveError(String; 성공이면 "") — 실패해도 예외를 던지지 않고 파일은 제자리에 둔다
movedPath = ""
moveError = ""
Try
    System.IO.Directory.CreateDirectory(destDir)
    Dim mvName As String = System.IO.Path.GetFileName(srcPath)
    Dim mvStem As String = System.IO.Path.GetFileNameWithoutExtension(mvName)
    Dim mvExt As String = System.IO.Path.GetExtension(mvName)
    Dim mvDest As String = System.IO.Path.Combine(destDir, mvName)
    If System.IO.File.Exists(mvDest) OrElse System.IO.Directory.Exists(mvDest) Then
        Dim mvN As Integer = 1
        Do While System.IO.File.Exists(System.IO.Path.Combine(destDir, mvStem & "_" & mvN.ToString() & mvExt)) OrElse System.IO.Directory.Exists(System.IO.Path.Combine(destDir, mvStem & "_" & mvN.ToString() & mvExt))
            mvN = mvN + 1
        Loop
        mvDest = System.IO.Path.Combine(destDir, mvStem & "_" & mvN.ToString() & mvExt)
    End If
    If Not System.IO.File.Exists(srcPath) Then Throw New System.IO.FileNotFoundException()
    System.IO.File.Move(srcPath, mvDest)
    movedPath = mvDest
Catch ex As System.Exception
    ' Python 의 예외 이름과 맞춘다 (FileNotFoundError / PermissionError / OSError)
    Dim mvLabel As String = "OSError"
    If TypeOf ex Is System.IO.FileNotFoundException OrElse TypeOf ex Is System.IO.DirectoryNotFoundException Then
        mvLabel = "FileNotFoundError"
    ElseIf TypeOf ex Is System.UnauthorizedAccessException Then
        mvLabel = "PermissionError"
    End If
    movedPath = ""
    moveError = "이동 실패(" & mvLabel & ")"
End Try
