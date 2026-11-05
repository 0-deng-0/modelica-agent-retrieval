# Modelica 离线检索

本项目为本地 Modelica 文档建立 BM25 词法索引，提供命令行（CLI）和 Python API。索引和查询在本地运行，不调用网络服务，也不依赖 embedding。

仓库当前包含 Modelica Standard Library 4.0.0 数据、Modelica Language Specification 3.6 数据，以及对应的已登记索引。

## 功能

- `search`：按查询词检索已登记文档，可指定文档、查询变体、结果数量和最低置信度。
- `get`：按 MSL 组件路径或规范章节路径获取记录，可选择返回字段。
- `list-docs`：列出当前已登记的可检索文档。
- `list-children`：浏览 MSL 包的直接子项，可按组件类型筛选。
- `build`：从 MSL 或规范章节 JSON 文件建立索引。
- `health`：查看已登记文档数量。

## 快速开始

在项目根目录运行以下命令。搜索指定 MSL 文档：

```powershell
python -m search.cli search --doc modelica-4.0.0 --query "PID controller" --pretty
```

搜索规范章节：

```powershell
python -m search.cli search --doc spec3.6 --query "equations" --pretty
```

按组件路径获取完整记录：

```powershell
python -m search.cli get --doc modelica-4.0.0 --path Modelica.Blocks.Continuous.LimPID --pretty
```

查看索引文档，或浏览包的直接子项：

```powershell
python -m search.cli list-docs --pretty
python -m search.cli list-children --doc modelica-4.0.0 --parent Modelica.Blocks --pretty
```

命令列表及参数说明：

```powershell
python -m search.cli --help
python -m search.cli search --help
```

## Python API

通过 `search.api.run_search_api` 调用与 CLI 对应的功能。业务结果位于响应的 `data` 字段中：

```python
from search.api import run_search_api

result = run_search_api(
	"search",
	doc_id="msl",
	query="PID controller",
	final_k=5,
)
for candidate in result["data"]["candidates"]:
	print(candidate["path"], candidate["confidence"])
```

获取指定组件记录，也可用 `fields` 限制返回字段：

```python
result = run_search_api(
	"get",
	doc_id="msl",
	paths=["Modelica.Blocks.Continuous.LimPID"],
	fields=["path", "name", "description"],
)
print(result["data"]["items"])
```

`run_search_api` 支持 `search`、`get`、`list-docs`、`list-children`、`build` 和 `health` 等操作。调用参数可参考 [search/api.py](search/api.py) 中的接口实现。

## 数据来源

本项目中的 Modelica 数据是基于以下公开资料整理并转换为 JSON，用于本地索引和检索：

- [Modelica Standard Library 4.0.0](https://github.com/modelica/ModelicaStandardLibrary/tree/v4.0.0)
- [Modelica Language Specification 3.6](https://specification.modelica.org/maint/3.6/)

Modelica 语言由 Modelica Association 开发。Modelica 相关原始资料及其权利归各自权利人所有；MSL 的 BSD 3-Clause 条款和规范的版权与分发条件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。本项目是独立的检索工具，不代表 Modelica Association，也未声称获得其认可。

## 许可证

根目录的 [MIT License](LICENSE) 适用于本项目自身的检索代码。仓库中的 Modelica 数据不由该 MIT 许可覆盖，仍受各自来源的版权及许可条件约束，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。