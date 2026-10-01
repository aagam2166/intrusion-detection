import json
import logging
import re
from pathlib import Path
import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")


def sanitize_label(label: str) -> str:
    """Sanitize label string to remove bad characters and standardize formatting."""
    if not isinstance(label, str):
        return "UNKNOWN"
    label = label.strip()
    # Fix non-ascii / bad encoding replacement characters (e.g. Web Attack  Brute Force)
    label = re.sub(r"[^\x00-\x7F]+", " - ", label)
    # Normalize multiple spaces or hyphen formatting
    label = re.sub(r"\s+", " ", label)
    label = label.replace("Web Attack - Brute Force", "Web Attack - Brute Force")
    label = label.replace("Web Attack - XSS", "Web Attack - XSS")
    label = label.replace("Web Attack - Sql Injection", "Web Attack - SQL Injection")
    return label


def clean_dataset(
    input_path: Path = PROCESSED_DIR / "merged_raw.csv",
    output_path: Path = PROCESSED_DIR / "cleaned_data.csv.gz",
    drop_duplicates: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """Cleans raw merged dataset by sanitizing labels, handling NaNs/Infs,

    removing duplicate rows, and dropping zero-variance features.
    """
    logger.info(f"Loading raw dataset from {input_path}...")
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    df = pd.read_csv(input_path, low_memory=False)
    initial_shape = df.shape
    logger.info(f"Initial dataset shape: {initial_shape}")

    # 1. Clean column names
    df.columns = df.columns.str.strip()

    # Locate label column
    label_col_candidates = [c for c in df.columns if c.lower() == "label"]
    if not label_col_candidates:
        raise KeyError(f"Label column not found in dataset columns: {list(df.columns)}")
    label_col = label_col_candidates[0]

    # 2. Sanitize class labels
    df[label_col] = df[label_col].apply(sanitize_label)
    logger.info("Class labels sanitized.")

    # 3. Handle Infinite and NaN values
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    # Replace inf with nan
    inf_count_before = np.isinf(df[num_cols]).sum().sum()
    df[num_cols] = df[num_cols].replace([np.inf, -np.inf], np.nan)

    nan_rows_before = df.isnull().any(axis=1).sum()
    logger.info(f"Replacing infinite values ({inf_count_before} occurrences)...")
    logger.info(f"Dropping {nan_rows_before} rows with missing or infinite values...")

    df = df.dropna().reset_index(drop=True)
    shape_after_nan = df.shape

    # 4. Drop duplicates if requested
    duplicates_dropped = 0
    if drop_duplicates:
        duplicates_count = df.duplicated().sum()
        logger.info(f"Found {duplicates_count} duplicate rows. Dropping...")
        df = df.drop_duplicates().reset_index(drop=True)
        duplicates_dropped = int(duplicates_count)

    shape_after_duplicates = df.shape

    # 5. Drop zero-variance (constant) features
    feature_cols = [c for c in df.columns if c != label_col]
    stds = df[feature_cols].std()
    zero_var_cols = stds[stds == 0].index.tolist()
    logger.info(f"Found {len(zero_var_cols)} constant features (std=0): {zero_var_cols}")

    if zero_var_cols:
        df = df.drop(columns=zero_var_cols)
        logger.info(f"Dropped {len(zero_var_cols)} zero-variance features.")

    final_shape = df.shape
    logger.info(f"Final cleaned shape: {final_shape}")

    # Label distribution summary
    label_dist = df[label_col].value_counts().to_dict()

    summary_metadata = {
        "initial_shape": list(initial_shape),
        "shape_after_nan_drop": list(shape_after_nan),
        "duplicates_dropped": duplicates_dropped,
        "zero_variance_cols_dropped": zero_var_cols,
        "final_shape": list(final_shape),
        "label_distribution": label_dist,
    }

    # Save summary metadata
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_DIR / "cleaning_summary.json", "w") as f:
        json.dump(summary_metadata, f, indent=4)

    # Save cleaned data
    logger.info(f"Saving cleaned dataset to {output_path}...")
    df.to_csv(output_path, index=False, compression="gzip")
    logger.info("Cleaned dataset successfully saved!")

    return df, summary_metadata


def main():
    clean_dataset()


if __name__ == "__main__":
    main()
