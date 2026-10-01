import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler
from sklearn.feature_selection import mutual_info_classif
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")

ATTACK_FAMILY_MAP = {
    "BENIGN": "BENIGN",
    "DDoS": "DDoS",
    "DoS Hulk": "DoS",
    "DoS GoldenEye": "DoS",
    "DoS slowloris": "DoS",
    "DoS Slowhttptest": "DoS",
    "PortScan": "PortScan",
    "FTP-Patator": "Brute Force",
    "SSH-Patator": "Brute Force",
    "Web Attack - Brute Force": "Web Attack",
    "Web Attack - SQL Injection": "Web Attack",
    "Web Attack - XSS": "Web Attack",
    "Bot": "Bot/Infiltration",
    "Infiltration": "Bot/Infiltration",
    "Heartbleed": "Bot/Infiltration",
}


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.replace(0, np.nan)).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)


def group_attack_families(labels: pd.Series) -> pd.Series:
    grouped = labels.map(ATTACK_FAMILY_MAP)
    unknown = labels[grouped.isna()].unique().tolist()
    if unknown:
        raise ValueError(f"Unmapped labels found: {unknown}")
    return grouped


def engineer_features(features: pd.DataFrame) -> pd.DataFrame:
    """Add sentinel indicators, stable ratios, and log transforms."""
    result = features.copy()

    for column in ("Init_Win_bytes_forward", "Init_Win_bytes_backward"):
        if column in result:
            result[f"has_{column}"] = (result[column] != -1).astype(np.int8)

    derived = {
        "fwd_bwd_packet_ratio": _safe_divide(
            result["Total Fwd Packets"], result["Total Backward Packets"]
        ),
        "fwd_bwd_byte_ratio": _safe_divide(
            result["Total Length of Fwd Packets"],
            result["Total Length of Bwd Packets"],
        ),
        "bytes_per_packet": _safe_divide(
            result["Total Length of Fwd Packets"]
            + result["Total Length of Bwd Packets"],
            result["Total Fwd Packets"] + result["Total Backward Packets"],
        ),
        "fwd_bytes_per_packet": _safe_divide(
            result["Total Length of Fwd Packets"], result["Total Fwd Packets"]
        ),
        "bwd_bytes_per_packet": _safe_divide(
            result["Total Length of Bwd Packets"], result["Total Backward Packets"]
        ),
        "fwd_bwd_header_ratio": _safe_divide(
            result["Fwd Header Length"], result["Bwd Header Length"]
        ),
        "active_idle_ratio": _safe_divide(
            result["Active Mean"], result["Idle Mean"]
        ),
    }
    result = pd.concat([result, pd.DataFrame(derived, index=result.index)], axis=1)

    for column in result.columns:
        values = result[column]
        if pd.api.types.is_numeric_dtype(values) and values.min() >= 0:
            if values.skew() > 1.0:
                result[f"log1p_{column}"] = np.log1p(values)

    return result.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def select_features(
    X_train: pd.DataFrame,
    y_binary: np.ndarray,
    y_multi: np.ndarray,
    max_features: int = 50,
    sample_size: int = 100_000,
) -> list[str]:
    """Select relevant features using correlations, MI, then redundancy pruning."""
    sample = X_train.sample(min(sample_size, len(X_train)), random_state=42)
    sample_indices = sample.index
    binary = pd.Series(y_binary, index=X_train.index).loc[sample_indices]
    multi = pd.Series(y_multi, index=X_train.index).loc[sample_indices]

    pearson_binary = X_train.loc[sample_indices].corrwith(binary).abs()
    spearman_binary = X_train.loc[sample_indices].corrwith(binary, method="spearman").abs()
    pearson_multi = X_train.loc[sample_indices].corrwith(multi).abs()
    spearman_multi = X_train.loc[sample_indices].corrwith(multi, method="spearman").abs()
    mi_binary = pd.Series(
        mutual_info_classif(sample, binary, random_state=42), index=sample.columns
    )
    mi_multi = pd.Series(
        mutual_info_classif(sample, multi, random_state=42), index=sample.columns
    )

    scores = pd.concat(
        [pearson_binary, spearman_binary, pearson_multi, spearman_multi, mi_binary, mi_multi],
        axis=1,
    ).max(axis=1).sort_values(ascending=False)
    candidates = scores.head(min(max_features * 2, len(scores))).index.tolist()

    selected: list[str] = []
    correlation_matrix = X_train.loc[sample_indices, candidates].corr().abs()
    for column in candidates:
        if all(correlation_matrix.loc[column, existing] <= 0.95 for existing in selected):
            selected.append(column)
        if len(selected) == max_features:
            break
    return selected


def _balance_training_set(
    X: np.ndarray,
    y: np.ndarray,
    task: str,
    random_state: int,
    max_class_samples: int,
) -> tuple[np.ndarray, np.ndarray, dict]:
    counts = pd.Series(y).value_counts().sort_index()
    undersample_limit = min(max_class_samples, int(counts.max()))
    under_strategy = {
        label: min(int(count), undersample_limit)
        for label, count in counts.items()
    }
    under = RandomUnderSampler(
        sampling_strategy=under_strategy, random_state=random_state
    )
    X_under, y_under = under.fit_resample(X, y)
    under_counts = pd.Series(y_under).value_counts().sort_index()

    if task == "binary":
        target_counts = {label: int(under_counts.max()) for label in under_counts.index}
    else:
        target_counts = {
            label: max(int(count), min(max_class_samples, int(under_counts.max())))
            for label, count in under_counts.items()
        }
    min_class_count = int(under_counts.min())
    if min_class_count < 2:
        raise ValueError("SMOTE requires at least two samples in every training class.")
    smote = SMOTE(
        sampling_strategy=target_counts,
        k_neighbors=min(5, min_class_count - 1),
        random_state=random_state,
    )
    X_balanced, y_balanced = smote.fit_resample(X_under, y_under)
    summary = {
        "before": {str(k): int(v) for k, v in counts.items()},
        "after_undersampling": {str(k): int(v) for k, v in under_counts.items()},
        "after_smote": {
            str(k): int(v) for k, v in pd.Series(y_balanced).value_counts().sort_index().items()
        },
    }
    return X_balanced, y_balanced, summary


def split_and_scale_dataset(
    input_path: Path = PROCESSED_DIR / "cleaned_data.csv.gz",
    train_size: float = 0.70,
    val_size: float = 0.15,
    test_size: float = 0.15,
    random_state: int = 42,
    max_class_samples: int = 200_000,
    max_selected_features: int = 50,
    balance_training: bool = True,
) -> dict:
    """Prepare leakage-safe grouped targets, selected features, and balanced training data."""
    assert abs(train_size + val_size + test_size - 1.0) < 1e-5, (
        "Splits must sum to 1.0"
    )

    logger.info(f"Loading cleaned dataset from {input_path}...")
    if not input_path.exists():
        raise FileNotFoundError(
            f"Cleaned dataset not found: {input_path}. Run clean_data.py first."
        )

    df = pd.read_csv(input_path, compression="gzip", low_memory=False)
    logger.info(f"Loaded dataset shape: {df.shape}")

    label_col = [c for c in df.columns if c.lower() == "label"][0]

    grouped_labels = group_attack_families(df[label_col])
    X = engineer_features(df.drop(columns=[label_col])).astype(np.float32)
    y_binary = (grouped_labels != "BENIGN").astype(np.int8).to_numpy()
    label_encoder = LabelEncoder()
    y_multi = label_encoder.fit_transform(grouped_labels)
    class_names = list(label_encoder.classes_)
    label_map = {int(i): str(name) for i, name in enumerate(class_names)}
    logger.info("Using attack families: %s", class_names)

    temp_size = val_size + test_size
    X_train, X_temp, y_train_multi, y_temp_multi, y_train_bin, y_temp_bin = (
        train_test_split(
            X,
            y_multi,
            y_binary,
            test_size=temp_size,
            stratify=y_multi,
            random_state=random_state,
        )
    )

    val_relative_ratio = val_size / temp_size
    X_val, X_test, y_val_multi, y_test_multi, y_val_bin, y_test_bin = (
        train_test_split(
            X_temp,
            y_temp_multi,
            y_temp_bin,
            test_size=(1.0 - val_relative_ratio),
            stratify=y_temp_multi,
            random_state=random_state,
        )
    )

    logger.info(f"Dataset split completed:")
    logger.info(
        f"  - Train shape: {X_train.shape} ({len(X_train)/len(df)*100:.1f}%)"
    )
    logger.info(f"  - Val shape:   {X_val.shape} ({len(X_val)/len(df)*100:.1f}%)")
    logger.info(
        f"  - Test shape:  {X_test.shape} ({len(X_test)/len(df)*100:.1f}%)"
    )

    engineered_feature_count = X_train.shape[1]
    selected_features = select_features(
        X_train,
        y_train_bin,
        y_train_multi,
        max_features=max_selected_features,
    )
    X_train = X_train[selected_features]
    X_val = X_val[selected_features]
    X_test = X_test[selected_features]

    logger.info("Selected %d features from engineered feature set.", len(selected_features))
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    X_test_scaled = scaler.transform(X_test)

    logger.info("Saving split datasets and scaler artifacts to disk...")

    # Scaled features & targets
    joblib.dump(X_train_scaled, PROCESSED_DIR / "X_train.joblib", compress=3)
    joblib.dump(X_val_scaled, PROCESSED_DIR / "X_val.joblib", compress=3)
    joblib.dump(X_test_scaled, PROCESSED_DIR / "X_test.joblib", compress=3)

    joblib.dump(y_train_bin, PROCESSED_DIR / "y_train_binary.joblib")
    joblib.dump(y_val_bin, PROCESSED_DIR / "y_val_binary.joblib")
    joblib.dump(y_test_bin, PROCESSED_DIR / "y_test_binary.joblib")

    joblib.dump(y_train_multi, PROCESSED_DIR / "y_train_multi.joblib")
    joblib.dump(y_val_multi, PROCESSED_DIR / "y_val_multi.joblib")
    joblib.dump(y_test_multi, PROCESSED_DIR / "y_test_multi.joblib")

    balance_summary = {}
    if balance_training:
        for task, target in (("binary", y_train_bin), ("multi", y_train_multi)):
            X_balanced, y_balanced, task_summary = _balance_training_set(
                X_train_scaled,
                target,
                task=task,
                random_state=random_state,
                max_class_samples=max_class_samples,
            )
            joblib.dump(X_balanced, PROCESSED_DIR / f"X_train_{task}_balanced.joblib", compress=3)
            joblib.dump(y_balanced, PROCESSED_DIR / f"y_train_{task}_balanced.joblib", compress=3)
            balance_summary[task] = task_summary

    joblib.dump(scaler, PROCESSED_DIR / "scaler.joblib")

    with open(PROCESSED_DIR / "feature_names.json", "w") as f:
        json.dump(selected_features, f, indent=4)

    with open(PROCESSED_DIR / "label_map.json", "w") as f:
        json.dump(label_map, f, indent=4)

    split_summary = {
        "feature_count": len(selected_features),
        "engineered_feature_count": engineered_feature_count,
        "total_samples": len(df),
        "splits": {
            "train": {
                "samples": len(X_train),
                "binary_pos_ratio": float(np.mean(y_train_bin)),
            },
            "validation": {
                "samples": len(X_val),
                "binary_pos_ratio": float(np.mean(y_val_bin)),
            },
            "test": {
                "samples": len(X_test),
                "binary_pos_ratio": float(np.mean(y_test_bin)),
            },
        },
        "label_map": label_map,
        "balance_training": balance_training,
        "balance_summary": balance_summary,
    }

    with open(PROCESSED_DIR / "split_summary.json", "w") as f:
        json.dump(split_summary, f, indent=4)

    logger.info("Splitting, scaling, and artifact saving finished successfully!")
    return split_summary


def main():
    split_and_scale_dataset()


if __name__ == "__main__":
    main()
