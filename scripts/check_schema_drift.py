from pathlib import Path
from tempfile import TemporaryDirectory

from vex_contracts.schema_export import export_schemas


def main() -> None:
    expected_root = Path("schemas")
    with TemporaryDirectory() as directory:
        generated_root = Path(directory)
        export_schemas(generated_root)
        expected_files = {path.name: path for path in expected_root.glob("*.json")}
        generated_files = {path.name: path for path in generated_root.glob("*.json")}
        if expected_files.keys() != generated_files.keys():
            raise SystemExit("schema file set differs from generated contracts")
        changed = [
            name
            for name in sorted(expected_files)
            if expected_files[name].read_bytes() != generated_files[name].read_bytes()
        ]
        if changed:
            raise SystemExit(f"schema drift detected: {', '.join(changed)}")


if __name__ == "__main__":
    main()
