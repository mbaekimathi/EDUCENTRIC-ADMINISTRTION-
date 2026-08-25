"""MySQL backend compatible with XAMPP's bundled MariaDB 10.4.



Django 6.1 officially requires MariaDB 10.11+ and enables INSERT ... RETURNING

for all MariaDB builds. XAMPP's 10.4 lacks RETURNING, so we keep the ORM and

migrations working against the DB named in .env.

"""



from django.db.backends.mysql.base import DatabaseWrapper as MysqlDatabaseWrapper

from django.db.backends.mysql.features import DatabaseFeatures as MysqlDatabaseFeatures

from django.utils.functional import cached_property





class DatabaseFeatures(MysqlDatabaseFeatures):

    @cached_property

    def can_return_columns_from_insert(self):

        # INSERT ... RETURNING arrived in MariaDB 10.5.

        return (

            self.connection.mysql_is_mariadb

            and self.connection.mysql_version >= (10, 5)

        )



    @cached_property

    def has_native_uuid_field(self):

        # Native UUID type arrived in MariaDB 10.7.

        return (

            self.connection.mysql_is_mariadb

            and self.connection.mysql_version >= (10, 7)

        )





class DatabaseWrapper(MysqlDatabaseWrapper):

    features_class = DatabaseFeatures



    def check_database_version_supported(self):

        return


