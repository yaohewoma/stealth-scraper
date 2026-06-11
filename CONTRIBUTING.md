# Contributing to Stealth Scraper

感谢你对 Stealth Scraper 的关注！以下指南将帮助你高效地参与贡献。

## 开发环境

```bash
# 克隆仓库
git clone https://github.com/yaohewoma/stealth-scraper.git
cd stealth-scraper

# 创建虚拟环境
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

# 安装依赖
pip install -r references/requirements.txt
pip install -r requirements-dev.txt  # 开发依赖
```

## 代码规范

- Python 3.8+，遵循 [PEP 8](https://pep8.org/)
- 所有函数必须有 docstring（Google 风格）
- 类型标注：公共函数必须标注参数和返回值类型
- 文件编码：UTF-8，换行符 LF
- 提交信息：遵循 [Conventional Commits](https://www.conventionalcommits.org/)

## 目录约定

```
stealth-scraper/
├── examples/        # 面向用户的入门示例
├── references/      # Skill 参考实现和文档
│   ├── *.py         # 可直接运行的 Python 脚本
│   └── *.md         # 模块设计文档
├── tests/           # 单元测试和集成测试
└── .github/         # CI 配置
```

## 提交流程

1. Fork 本仓库
2. 从 `main` 分支创建 feature 分支：`git checkout -b feat/your-feature`
3. 编写代码并添加测试
4. 运行 `pre-commit run --all-files` 确保代码风格一致
5. 提交 PR，描述改动目的和测试情况

## 新增模块指南

如果要新增一个可选模块（如新的指纹来源、代理策略等），请遵循以下模式：

```
references/
└── your-new-module.md    # 模块文档（配置、用法、注意事项）
```

模块文档模板：

```markdown
# 模块名称

## 概述
简要描述模块解决的问题。

## 配置
```python
CONFIG = { "key": "value" }
```

## 实现
核心代码片段（简化但可理解）。

## 使用示例
最简可运行示例。

## 注意事项
1. 兼容性问题
2. 性能注意事项
```

## 问题反馈

- Bug 报告：附带 Python 版本、依赖版本、最小复现步骤、错误日志
- 功能请求：描述使用场景和期望行为
- 文档改进：直接提 PR

## 行为准则

请保持专业、尊重、建设性的交流氛围。