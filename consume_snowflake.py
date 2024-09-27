import os, traceback
import pandas as pd
from uuid import uuid4
import snowflake.connector as snowconn
from xpms_file_storage.file_handler import XpmsResource, LocalResource

NAMESPACE = os.getenv("MINIO_BUCKET_NAME", "DEFAULT")


class ConsumeSnowflake:
    user_name = None
    password = None
    account_identifier = None
    query = None
    merge_data = False
    foreign_key = None
    warehouse = None
    database = None
    schema = None
    role = None
    method = None

    def __init__(self, config=None, in_obj=None):
        self.__dict__.update(**config)
        self.config = config
        self.in_obj = in_obj

    def get(self):
        try:
            self.__validate()
            connection = self.__get_db_connection()
            cursor = connection.cursor()
            records = cursor.execute(self.query).fetchall()
            cols = [desc[0] for desc in cursor.description]
            collected_df = pd.DataFrame(records, columns=cols)
            if not records:
                msg = "No record found with the given query or Table is Empty!"
                raise Exception(msg)
            if self.merge_data and not self.in_obj.empty and self.foreign_key:
                df = pd.merge(self.in_obj, collected_df, on=self.foreign_key, how='left')
                return self.__upload_to_minio(df)
            return self.__upload_to_minio(collected_df)
        except Exception as e:
            raise e
        finally:
            cursor.close()
            connection.close()

    def insert(self):
        try:
            self.__validate()
            snowflake_db = self.__get_db_connection()
            connection = snowflake_db.connect()
            connection.execute(self.query)
            return self.in_obj
        except Exception as e:
            raise e
        finally:
            connection.close()
            snowflake_db.dispose()

    def update(self):
        try:
            self.__validate()
            snowflake_db = self.__get_db_connection()
            connection = snowflake_db.connect()
            connection.execute(self.query)
            return self.in_obj
        except Exception as e:
            raise e
        finally:
            connection.close()
            snowflake_db.dispose()

    def __validate(self):
        """
        validate required config
        :return: None
        """
        if not self.user_name:
            raise KeyError("'user name' is required in config")
        if not self.password:
            raise KeyError("'password' is required in config")
        if not self.account_identifier:
            raise KeyError("'account identifier' is required in config")
        if not self.query:
            raise KeyError("'query' is required in config")
        if not self.warehouse:
            raise KeyError("'warehouse' is required in config")
        if not self.database:
            raise KeyError("'database' is required in config")

    def __upload_to_minio(self, _df):
        local_path = "/tmp/{}.csv".format(str(uuid4()))
        _df.to_csv(local_path, index=False)
        xrm = XpmsResource()
        lr = LocalResource(key=local_path)
        _minio_path = "minio://{NAMESPACE}/{SOLUTION_ID}/snowflake_data/{EXE_ID}.csv".format(
            NAMESPACE=NAMESPACE, SOLUTION_ID=self.config["context"]["solution_id"],
            EXE_ID=self.config["context"]["dag_execution_id"])
        mr = xrm.get(urn=_minio_path)
        lr.copy(mr)
        self.__remove_local_file(local_path)
        return _minio_path

    def __get_db_connection(self):
        """
        Returns DB for Application data
        :return: Application DB name
        """
        config = {"user": self.user_name, "password": self.password, "account": self.account_identifier,
                  "warehouse": self.warehouse, "database": self.database, "schema": self.schema, "role": self.role}
        conn = snowconn.connect(**config)
        return conn

    def __remove_local_file(self, path):
        if os.path.exists(path):
            os.remove(path)
        return


def consume_snowflake(config=None, **objects):
    try:
        conn = ConsumeSnowflake(config=config, in_obj=objects)
        if conn.method == "GET":
            return conn.get()
        if conn.method == "INSERT":
            return conn.insert()
        if conn.method == "UPDATE":
            return conn.update()
    except Exception as e:
        # todo: add cleanup code if requires
        return traceback.format_exc()
