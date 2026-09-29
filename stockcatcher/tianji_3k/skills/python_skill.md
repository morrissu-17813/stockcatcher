# Tianji 3K Python Skill

- Python 3.10+
- 型別標註
- dataclass / Enum 優先
- 核心策略函式保持純函式、可測試
- 外部 API 與策略邏輯分離
- 不在程式內硬編 API Key
- 共用上層 stockcatcher/.env
- 所有時間欄位明確標示 timezone
- 不使用未來資料造成 look-ahead bias
