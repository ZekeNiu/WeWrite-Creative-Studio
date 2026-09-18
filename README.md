# WeWrite Creative Studio

Windows 本地公众号创作工作台。支持选题、资料整理、大纲、写作、审核、配图与排版导出。

## 开始使用

安装 Python 3.11 或更新版本，下载本仓库后双击 **启动工作台.bat**。首次启动会安装 Python 依赖；仓库包含预构建界面，日常使用不需要 Node.js。退出后台请使用 **停止工作台.bat**。

打开“AI 服务与设置”添加自己的服务地址、API Key 和模型。每个模型可分别测试文本、图片和联网能力。联网接入与文本协议分开配置；在“流程偏好”选择实际使用的联网模型。

默认先使用已有资料，再由模型联网查找缺失依据；必要时使用已启用的后备渠道。素材支持 PDF、Word、Markdown、TXT、BibTeX、RIS、网页和粘贴文字。

完整操作说明见 [使用说明](使用说明.md)，版本记录见 [CHANGELOG](CHANGELOG.md)。

工作流暂停时可逐项核实、补充材料或选择保留边界后继续；前置条件不足的生成操作会显示处理入口。

## 输出与数据

- `output/articles/`：按文章和版本归档的 Markdown、HTML、图片、来源清单及 ZIP。
- `output/diagnostics/`：测试报告、截图、连接测试图片。
- `output/test-workspaces/`：隔离测试环境。
- `data/`：仅保存在本机的文章、素材、历史版本和加密凭证；日志在 `data/logs/`，浏览器缓存位于 `data/cache/`。

这些个人数据目录均不进入 Git。公开仓库只包含程序、模拟测试和文档。API Key 使用 Windows 当前用户加密，换电脑或 Windows 用户后需重新填写。使用云模型或搜索服务时，相应任务内容会发送到用户配置的服务。

## 开发与检查

前端使用 React / TypeScript / Vite，后端使用 FastAPI / SQLite。

```powershell
npm ci
npm run build
.venv/Scripts/python.exe -m pytest -q
```

`dist/` 随源码提交以支持双击运行；修改前端后需重新构建。测试默认使用临时数据目录。`tools/qa_v14_app.py` 和 `tools/qa_v141_app.py` 仅用于模拟界面验收，不由正式启动器加载。

旧输出整理：先执行 `.venv/Scripts/python.exe tools/organize_outputs.py` 查看清单，再附加 `--apply` 执行。只移动已知产物，不覆盖已有目标文件。

## 上游

本项目包含固定版本 WeWrite 4.2.1，见 [上游版本](vendor/wewrite/UPSTREAM_REVISION) 和 [上游 MIT 许可证](vendor/wewrite/LICENSE)。

素材页面支持整理结果／素材列表页签、每页 10 条、折叠及筛选后的批量采用。仅在有特殊意图时填写“使用要求（可选）”；关联主张和大纲章节可在素材详情查看，个人经历仍需明确授权。
