# 시험 세트2를 Runtime 폴더로 복사한다
$u = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force "$u\Runtime\inbox","$u\Runtime\out" | Out-Null
Copy-Item "$PSScriptRoot\audio\*" "$u\Runtime\inbox" -Force
Copy-Item "$PSScriptRoot\out\*.json" "$u\Runtime\out" -Force
"복사 완료"
