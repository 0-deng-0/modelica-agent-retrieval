import json
import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from search import api
else:
    from . import api

#本文档仅用于功能测试，不影响功能实现

def main() -> None:
    """Simple build/list-docs/search/get examples using a temporary registry."""
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        msl_json = temp / "sample-msl.json"
        spec_json = temp / "sample-spec.json"
        original_index_dir = api.INDEX_DIR
        original_registry_path = api.REGISTRY_PATH
        api.INDEX_DIR = temp / "index"
        api.REGISTRY_PATH = api.INDEX_DIR / "index.json"

        try:
            msl_json.write_text(
                json.dumps(
                    [
                        {
                            "path": "Modelica.Test.PID",
                            "name": "PID",
                            "kind": "block",
                            "description": "PID controller",
                            "information": "Proportional integral derivative controller",
                            "interface": [],
                            "model": "block PID end PID;",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            spec_json.write_text(
                json.dumps(
                    [
                        {
                            "section_path": "Expressions.Arithmetic",
                            "url": "https://example.test/spec#arithmetic",
                            "content": "Arithmetic expressions and operators.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            # Build example: create one index per source JSON.
            print(
                "BUILD MSL:",
                api.run_search_api(
                    "build",
                    input_json_path=str(msl_json),
                    format="msl",
                    doc_id="modelica-test",
                ),
            )
            print(
                "BUILD SPEC:",
                api.run_search_api(
                    "build",
                    input_json_path=str(spec_json),
                    format="spec",
                    doc_id="spec-test",
                ),
            )

            # List registered documents.
            docs_result = api.run_search_api("list-docs")
            print("LIST DOCS:", json.dumps(docs_result, ensure_ascii=False, indent=2))

            # Search example.
            search_result = api.run_search_api(
                "search",
                doc_id="modelica-test",
                query="PID controller",
                final_k=5,
            )
            print(
                "SEARCH:",
                json.dumps(search_result["data"]["candidates"], ensure_ascii=False, indent=2),
            )

            # Get example: retrieve full records by a Modelica path.
            get_result = api.run_search_api(
                "get",
                doc_id="modelica-test",
                paths=["Modelica.Test.PID"],
            )
            print("GET:", json.dumps(get_result, ensure_ascii=False, indent=2))

            # List-children example: browse a package without reading every record.
            children_result = api.run_search_api(
                "list-children",
                doc_id="modelica-test",
                parent="Modelica.Test",
            )
            print("CHILDREN:", json.dumps(children_result, ensure_ascii=False, indent=2))
        finally:
            api.INDEX_DIR = original_index_dir
            api.REGISTRY_PATH = original_registry_path


if __name__ == "__main__":
    main()
#     children_result = api.run_search_api(
#     "list-children",
   
#     parent="Modelica",
# )
#     print("CHILDREN:", json.dumps(children_result, ensure_ascii=False, indent=2))
    docs_result=api.run_search_api("list-docs")
    print("LIST DOCS:", json.dumps(docs_result, ensure_ascii=False, indent=2))

        # Search example.
    search_result = api.run_search_api(
        "search",
        doc_id="msl",
        query="PID controller",
        final_k=5,
    )
    print(
        "SEARCH:",
        json.dumps(search_result["data"]["candidates"], ensure_ascii=False, indent=2),
    )
        # Get example: retrieve full records by a Modelica path.
    get_result = api.run_search_api(
        "get",
        paths=["Modelica.Blocks.Continuous.LimPID"],
    )
    print("GET:", json.dumps(get_result, ensure_ascii=False, indent=2))