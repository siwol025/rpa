' Step8: 입력 폴더의 처리 대상 파일 목록  (Python: run_folder.list_inputs)
' In : inDir(String) 입력 폴더
' Out: fileList(List(Of String)) 파일 경로, 이름순(코드 단위 순). 하위 폴더는 들어가지 않고, 숨김·임시 파일은 건드리지 않는다
'      (.으로 시작, ~$으로 시작, Thumbs.db, desktop.ini)
fileList = New System.Collections.Generic.List(Of String)
If System.IO.Directory.Exists(inDir) Then
    Dim names As New System.Collections.Generic.List(Of String)
    For Each f As String In System.IO.Directory.GetFiles(inDir)
        Dim n As String = System.IO.Path.GetFileName(f)
        Dim lower As String = n.ToLowerInvariant()
        If Not (n.StartsWith(".", System.StringComparison.Ordinal) OrElse n.StartsWith("~$", System.StringComparison.Ordinal) OrElse lower = "thumbs.db" OrElse lower = "desktop.ini") Then
            names.Add(n)
        End If
    Next
    names.Sort(System.StringComparer.Ordinal)
    For Each n As String In names
        fileList.Add(System.IO.Path.Combine(inDir, n))
    Next
End If
