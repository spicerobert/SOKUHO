-- ============================================================
-- 正式機：把 prepare_prod_bak.py 產出的 .bak 還原成 PosInsight，並建專用帳號（名稱 = SOKUHO .env 的 DB_USER）
-- 容器：integration_pos_db（Integration_of_POS 的 SQL Server，host port 1434）
--
-- 執行（PowerShell，在正式機的 SOKUHO 專案根目錄）：
--   docker cp "<SOKUHO_BAK_DEST>\migration\<檔>.bak" integration_pos_db:/var/opt/mssql/backup/
--   docker cp db\prod_restore.sql integration_pos_db:/tmp/prod_restore.sql
--   docker exec -it integration_pos_db /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -C -b `
--     -i /tmp/prod_restore.sql -v BAK='<檔>.bak' ETL_LOGIN='<DB_USER>' ETL_PASSWORD='<DB_PASSWORD>'
--   （密碼用單引號，避免 PowerShell 展開 $；sa 密碼互動輸入；ETL_PASSWORD 之後寫進 SOKUHO 的 .env 的 DB_PASSWORD）
--   docker exec integration_pos_db rm -f /var/opt/mssql/backup/<檔>.bak /tmp/prod_restore.sql
--
-- 已有 PosInsight 時會中止，不覆蓋（要重來請先人工確認再 DROP）。
-- ============================================================
:on error exit
SET NOCOUNT ON;
USE master;
GO

IF DB_ID(N'PosInsight') IS NOT NULL
    THROW 50001, N'PosInsight 已存在，中止還原（不覆蓋）。', 1;
GO

RESTORE DATABASE [PosInsight]
FROM DISK = N'/var/opt/mssql/backup/$(BAK)'
WITH MOVE N'PosInsight'     TO N'/var/opt/mssql/data/PosInsight.mdf',
     MOVE N'PosInsight_log' TO N'/var/opt/mssql/data/PosInsight_log.ldf',
     CHECKSUM, RECOVERY;
GO

-- 只做完整備份、不做 log 備份（同 Integration_of_POS 的 POS）
ALTER DATABASE [PosInsight] SET RECOVERY SIMPLE;
GO

-- 專用帳號：PosInsight 的 db_owner（ETL 會 MERGE / DELETE），不碰 POS 庫
IF SUSER_ID(N'$(ETL_LOGIN)') IS NULL
    CREATE LOGIN [$(ETL_LOGIN)] WITH PASSWORD = N'$(ETL_PASSWORD)', CHECK_POLICY = ON, DEFAULT_DATABASE = [PosInsight];
GO
-- RESTORE VERIFYONLY（backup_sokuho_db.py）需要 CREATE ANY DATABASE
GRANT CREATE ANY DATABASE TO [$(ETL_LOGIN)];
GO

USE [PosInsight];
GO
IF USER_ID(N'$(ETL_LOGIN)') IS NULL
    CREATE USER [$(ETL_LOGIN)] FOR LOGIN [$(ETL_LOGIN)];
ALTER ROLE db_owner ADD MEMBER [$(ETL_LOGIN)];
GO

SELECT DB_NAME() AS db,
       DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS collation,
       DATABASEPROPERTYEX(DB_NAME(), 'Recovery')  AS recovery,
       (SELECT COUNT(*) FROM sys.tables) AS tables,
       (SELECT COUNT(*) FROM sys.views)  AS views,
       (SELECT MAX(report_date) FROM dbo.fact_sales) AS max_report_date;
GO
