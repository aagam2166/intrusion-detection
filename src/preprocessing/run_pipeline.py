import argparse
import logging
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.preprocessing.clean_data import clean_dataset
from src.preprocessing.inspect_and_merge import main as merge_raw_files
from src.preprocessing.split_and_scale import split_and_scale_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

RAW_MERGED_PATH = Path("data/processed/merged_raw.csv")
CLEANED_PATH = Path("data/processed/cleaned_data.csv.gz")


def run_full_pipeline(force_remerge: bool = False):
    """Executes the end-to-end data preprocessing pipeline:

    1. Raw Data Merging (if needed)
    2. Data Cleaning & Sanitization
    3. Stratified Splitting & Feature Scaling
    """
    start_time = time.time()
    logger.info("=" * 70)
    logger.info("STARTING INTRUSION DETECTION DATA PREPROCESSING PIPELINE")
    logger.info("=" * 70)

    # Step 1: Merge raw CSVs if not present or forced
    if not RAW_MERGED_PATH.exists() or force_remerge:
        logger.info("\n--- STEP 1: MERGING RAW CSV FILES ---")
        merge_raw_files()
    else:
        logger.info(
            f"\n--- STEP 1: SKIPPED (Merged file already exists at {RAW_MERGED_PATH}) ---"
        )

    # Step 2: Data Cleaning
    logger.info("\n--- STEP 2: CLEANING DATASET ---")
    _, clean_summary = clean_dataset(
        input_path=RAW_MERGED_PATH, output_path=CLEANED_PATH
    )

    # Step 3: Dataset Splitting & Scaling
    logger.info("\n--- STEP 3: SPLITTING & SCALING DATASET ---")
    split_summary = split_and_scale_dataset(input_path=CLEANED_PATH)

    elapsed_time = time.time() - start_time
    logger.info("\n" + "=" * 70)
    logger.info(f"PREPROCESSING PIPELINE COMPLETED SUCCESSFULLY IN {elapsed_time:.2f}s!")
    logger.info(f"Summary Report:")
    logger.info(f"  - Cleaned Samples: {clean_summary['final_shape'][0]:,}")
    logger.info(f"  - Features Retained: {split_summary['feature_count']}")
    logger.info(
        f"  - Train Set Size: {split_summary['splits']['train']['samples']:,}"
    )
    logger.info(
        f"  - Validation Set Size: {split_summary['splits']['validation']['samples']:,}"
    )
    logger.info(
        f"  - Test Set Size: {split_summary['splits']['test']['samples']:,}"
    )
    logger.info("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run intrusion detection preprocessing pipeline."
    )
    parser.add_argument(
        "--force-remerge",
        action="store_true",
        help="Force re-merging raw CSV files",
    )
    args = parser.parse_args()

    run_full_pipeline(force_remerge=args.force_remerge)
