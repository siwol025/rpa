# 시험 세트를 Runtime 폴더로 복사한다 (Main_Audio 실행 전에 한 번 실행)
$u = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force "$u\Runtime\inbox","$u\Runtime\out" | Out-Null
Copy-Item "$PSScriptRoot\audio\*" "$u\Runtime\inbox" -Force
Copy-Item "$PSScriptRoot\out\*.json" "$u\Runtime\out" -Force
"복사 완료: 음성 $((Get-ChildItem "$PSScriptRoot\audio").Count)개 → Runtime\inbox, 결과 JSON $((Get-ChildItem "$PSScriptRoot\out").Count)개 → Runtime\out"
