但有三件事会让它到那边直接跑不起来，得先处理
① runtime 918M 里 870M 是 runtime\ov（记忆层 venv），而测试版根本不用它。​ 服务器上只 debug 采集链路的话，带 runtime\python（48M）就够 —— 只要不启动 ov 记忆层就不需要 ov venv。带上是 966M，不带是约 96M。

② config.json 里有一个真实 API key。​

json

"base_url": "http://<API_HOST>",
"api_key": "<YOUR_API_KEY>",
api_key 留空就是离线演示模式（不出网、内置离线引擎出牌）。debug 采集链路不需要真模型，建议先把 key 清空再打包，顺手也避免密钥落到别处。

③ 端口 8792 在 server.py 里写死了，服务器上如果撞了要改 Cowrite-test/app/server.py 顶部那行。

需要带哪些

添加到对话
必须	说明
app/ 整个	2.1M，含改动的 server.py、web/index.html 与新增的 v3/probe.py、v3/probe_analyze.py
runtime/python/	48M 运行时
启动测试版.py	入口
探针使用说明.md	装置怎么用
assets/ 46M	前端资源，建议带
不用带：装桌面图标.py（服务器上没有桌面）、CowriteLauncher.ps1 与 旧版-启动脚本-不要用.ps1（PowerShell 那条路已废，改用 Python 版）、licenses/（可省）、data/。

你要带的数据也在里面
app/v3/logs/probe.jsonl（37.6K）和 samples.jsonl（30K）——里面已经有你今晚写的东西。带上它，服务器上直接跑 probe_analyze.py 就能看到你标的那些数，不需要重新等数据。

那边怎么起
bash

cd Cowrite-test
./runtime/python/python.exe 启动测试版.py --no-open
然后 curl -X POST http://127.0.0.1:8792/api/probe/stats -d '{}' 探活。注意今晚那个"起来几秒就死"的问题，我在这台机器上复现并定位到了（CREATE_NEW_PROCESS_GROUP 那行），但没在别的机器上验证过 —— 如果那边也起不来就死，先看 test-launcher.log 和 test-launcher.err，那两行 Start() 前的诊断会指出卡在哪一步。