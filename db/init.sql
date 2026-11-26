IF DB_ID('catalog') IS NULL CREATE DATABASE catalog;
IF DB_ID('matches') IS NULL CREATE DATABASE matches;
GO
IF SUSER_ID('catalog_app') IS NULL CREATE LOGIN catalog_app WITH PASSWORD = '$(CATALOG_DB_PASSWORD)';
IF SUSER_ID('matches_app') IS NULL CREATE LOGIN matches_app WITH PASSWORD = '$(MATCHES_DB_PASSWORD)';
GO
USE catalog;
IF USER_ID('catalog_app') IS NULL CREATE USER catalog_app FOR LOGIN catalog_app;
ALTER ROLE db_ddladmin ADD MEMBER catalog_app;
ALTER ROLE db_datareader ADD MEMBER catalog_app;
ALTER ROLE db_datawriter ADD MEMBER catalog_app;
GO
USE matches;
IF USER_ID('matches_app') IS NULL CREATE USER matches_app FOR LOGIN matches_app;
ALTER ROLE db_ddladmin ADD MEMBER matches_app;
ALTER ROLE db_datareader ADD MEMBER matches_app;
ALTER ROLE db_datawriter ADD MEMBER matches_app;
GO
-- catalog_app has no user in matches and matches_app has none in catalog: neither can open the other's database.