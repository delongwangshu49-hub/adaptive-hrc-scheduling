# 锁定前端工具链审计

2026-11-01本地执行npm ci和npm audit。沿用已锁定Vite 8.0.0，未升级或自动修复依赖。npm报告1个high依赖项（vite），含多条上游告警；完整结果见[npm_audit_snapshot.json](npm_audit_snapshot.json)。这是尚未修复的工具链限制，不记为依赖安全检查全通过。

上游[WebSocket任意文件读取告警](https://github.com/vitejs/vite/security/advisories/GHSA-p9ff-h696-f583)列明受影响8.0.0–8.0.4及开发服务器网络暴露/WebSocket条件；[查询绕过告警](https://github.com/vitejs/vite/security/advisories/GHSA-v2wj-q39q-566r)也适用于开发服务器。此次候选只执行静态构建，工作台加载打包的静态文件，没有启动或暴露Vite开发服务器；这不表示已修复该依赖，也不评定其他运行方式安全。

本包保留既有设计/依赖版本和科学运行身份。后续依赖更新须独立绑定版本及重新核对前端构建/交互；本次P063-R1有限修复不扩大为工具链升级。审阅发布候选时一并保留本项OPEN和原性能/人工/原生边界。
