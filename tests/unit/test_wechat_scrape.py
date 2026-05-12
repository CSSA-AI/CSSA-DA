import sys
import os
import json
import pytest
import requests  # 修复 NameError
from unittest.mock import patch, MagicMock

# 动态将 scripts 目录加入环境变量
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))

import wechat_article_scrape as scraper

class TestWechatScraper:
    """测试微信爬虫的 ETL 流程 (包含状态管理和文件合并)"""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, tmp_path):
        """核心隔离机制：使用 pytest 临时目录保护真实数据文件"""
        self.original_data_dir = scraper.DATA_DIR
        self.original_temp_dir = scraper.TEMP_DIR
        self.original_state_file = scraper.STATE_FILE
        self.original_final_file = scraper.FINAL_FILE

        scraper.DATA_DIR = str(tmp_path / "data")
        scraper.TEMP_DIR = str(tmp_path / "data" / "temp_chunks")
        scraper.STATE_FILE = str(tmp_path / "data" / "scraper_state.json")
        scraper.FINAL_FILE = str(tmp_path / "data" / "wechat_articles_all.json")

        scraper.init_environment()
        yield  
        
        scraper.DATA_DIR = self.original_data_dir
        scraper.TEMP_DIR = self.original_temp_dir
        scraper.STATE_FILE = self.original_state_file
        scraper.FINAL_FILE = self.original_final_file

    def test_state_management_serialization(self):
        """测试状态的存取逻辑：重点测试 set 集合转 JSON 列表是否正常"""
        mock_state = {
            "begin": 40,
            "total_saved": 40,
            "valid_count": 35,
            "seen_links": {"linkA", "linkB"}
        }

        scraper.save_state(mock_state)

        assert os.path.exists(scraper.STATE_FILE)
        loaded_state = scraper.load_state()
        assert loaded_state["begin"] == 40
        assert isinstance(loaded_state["seen_links"], set)
        assert "linkA" in loaded_state["seen_links"]

    def test_merge_and_cleanup(self, tmp_path):
        """测试最后的分块合并与无痕清理逻辑"""
        batch1 = [{"title": "文章1", "link": "url1"}]
        batch2 = [{"title": "文章2", "link": "url2"}]
        
        with open(os.path.join(scraper.TEMP_DIR, "batch_0.json"), "w") as f:
            json.dump(batch1, f)
        with open(os.path.join(scraper.TEMP_DIR, "batch_20.json"), "w") as f:
            json.dump(batch2, f)
            
        with open(scraper.STATE_FILE, "w") as f:
            json.dump({"begin": 40}, f)

        mock_state = {"total_saved": 2, "valid_count": 2}
        scraper.merge_and_cleanup(mock_state)

        assert os.path.exists(scraper.FINAL_FILE)
        with open(scraper.FINAL_FILE, "r") as f:
            final_data = json.load(f)
            assert len(final_data) == 2
            assert final_data[0]["title"] == "文章1"

        assert not os.path.exists(scraper.TEMP_DIR)
        assert not os.path.exists(scraper.STATE_FILE)

    @patch('wechat_article_scrape.requests.get')
    def test_api_network_error_handling(self, mock_get):
        """测试网络超时及最后合并结束机制"""
        
        # 1. 模拟第一页获取成功
        mock_list_response = MagicMock()
        mock_list_response.json.return_value = {
            "base_resp": {"ret": 0},
            "articles": [{"title": "测试文章", "link": "fake_url", "create_time": 123456789}]
        }
    
        # 2. 模拟第二页见底 (重点: 必须包含 "base_resp": {"ret": 0}，防止被判断为 API 失效)
        empty_response = MagicMock()
        empty_response.json.return_value = {
            "base_resp": {"ret": 0}, 
            "articles": []
        }

        mock_get.side_effect = [
            mock_list_response,               # 请求 1：获取文章列表 (成功)
            requests.exceptions.Timeout(),    # 请求 2：下载正文 (抛出超时错误)
            empty_response                    # 请求 3：下一页获取列表 (空，触发停止合并)
        ]
    
        with patch('builtins.print'):
            scraper.fetch_pipeline()
    
        assert os.path.exists(scraper.FINAL_FILE)
        
        with open(scraper.FINAL_FILE, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["title"] == "测试文章"
            assert data[0]["content"] == ""