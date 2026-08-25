import pandas as pd
from pathlib import Path

RAW_DIR = Path("data/raw")
OUT_DIR = Path("data/processed")
OUT_DIR.mkdir(parents=True, exist_ok=True)

def load_and_inspect(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)

    df.colums = df.columns.str.strip()

    print(f"\n{'='*60}")
    print(f"File: {path.name}")
    print(f"Shape: {df.shape}")
    print(f"Columns: {len(df.columns)}")

    label_col = next((c for c in df.columns if c.lower() == 'label'), None)

    if label_col:
        print(f"\nLabel distribution:")
        print(df[label_col].value_counts())

    else:
        print("Warning: no 'Label' column found int this file --check manually.")

    return df

def main():
    csv_files = sorted(RAW_DIR.glob("*.csv"))

    if not csv_files:
        print(f"No CSV files found in {RAW_DIR.resolve()}")
        print("Check if files exist")

        return

    print(f"Found {len(csv_files)} CSV file(s) in {RAW_DIR}:")

    for f in csv_files:
        print(f"  - {f.name}")

    dfs = [load_and_inspect(f) for f in csv_files]

    merged = pd.concat(dfs, ignore_index=True)

    print(f"\n{'='*60}")
    print(f"Merged Shape: {merged.shape}")

    label_col = next((c for c in merged.columns if c.lower() == 'label'),None)

    if label_col:
        print(f"\nCombined label distribution across all files:")
        print(merged[label_col].value_counts())

    out_path = OUT_DIR/"merged_raw.csv"
    merged.to_csv(out_path,index=False)
    print(f"\nSaved merged (uncleaned) data to {out_path}")


if __name__ == "__main__":
    main()