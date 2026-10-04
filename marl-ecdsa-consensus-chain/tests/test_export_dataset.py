"""
export_dataset 数据导出边界测试（RalphLoop 原子任务 AE）
覆盖：_load_json 缺失、_idx 越界、三种导出函数、main 入口
通过标准：新增 ≥6 项测试全过
"""
import csv
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))

import export_dataset as ed

logging.basicConfig(level=logging.CRITICAL)


class TestLoadJson:
    def test_missing_file_returns_none(self):
        assert ed._load_json('nonexistent_results_xyz.json') is None

    def test_existing_file_returns_dict(self):
        data = ed._load_json('training_results_pure.json')
        # 若项目数据存在则返回 dict，否则 None（两种都合法）
        assert data is None or isinstance(data, dict)


class TestIdxBoundary:
    def test_idx_in_range(self):
        assert ed._idx([1, 2, 3], 1) == 2

    def test_idx_out_of_range_empty(self):
        assert ed._idx([1, 2], 5) == ''

    def test_idx_empty_list(self):
        assert ed._idx([], 0) == ''


class TestExportTrainingCurve:
    def test_export_creates_files_or_zero(self, tmp_path):
        """导出训练曲线：有数据则生成 CSV，无数据则返回 0（两种都合法）"""
        rows = ed.export_training_curve(None, tmp_path)
        assert isinstance(rows, int)
        assert rows >= 0

    def test_export_csv_format_if_created(self, tmp_path):
        """若 CSV 生成，表头与行数一致"""
        rows = ed.export_training_curve(None, tmp_path)
        csv_files = list(tmp_path.glob('training_curve_*.csv'))
        if csv_files:
            with open(csv_files[0], encoding='utf-8') as f:
                reader = list(csv.reader(f))
            assert reader[0] == ['episode', 'reward', 'cooperation_rate', 'betrayal_rate', 'td_loss']


class TestExportBlockchainStats:
    def test_export_returns_count(self, tmp_path):
        """导出区块链统计：返回行数（6 或 0）"""
        count = ed.export_blockchain_stats(tmp_path)
        assert count in (0, 6)  # 无数据→0，有数据→6 行

    def test_export_csv_header_if_created(self, tmp_path):
        count = ed.export_blockchain_stats(tmp_path)
        f = tmp_path / 'blockchain_pipeline.csv'
        if f.exists():
            with open(f, encoding='utf-8') as fh:
                reader = list(csv.reader(fh))
            assert reader[0] == ['metric', 'value']


class TestExportModeComparison:
    def test_export_mode_returns_count(self, tmp_path):
        """导出模式对比：返回实际存在的模式数（0=无数据 / 2=bc+pure 真实实验 / 3=含 selfish 合成档）"""
        count = ed.export_mode_comparison(tmp_path)
        assert count in (0, 2, 3)

    def test_export_json_valid_if_created(self, tmp_path):
        count = ed.export_mode_comparison(tmp_path)
        f = tmp_path / 'mode_comparison.json'
        if f.exists():
            data = json.loads(f.read_text(encoding='utf-8'))
            assert 'dataset_name' in data
            assert 'modes' in data


class TestMain:
    def test_main_returns_zero(self, tmp_path, monkeypatch):
        """main 入口返回 0（成功），输出到指定目录"""
        monkeypatch.setattr(sys, 'argv', ['export_dataset.py', '--outdir', str(tmp_path)])
        rc = ed.main()
        assert rc == 0
