# Generated manually for MySQL ENUM dropdowns (phpMyAdmin / DB editors).



from django.db import migrations





ROLE_ENUM = (

    "'EMPLOYEE',"

    "'HEAD_OF_INSTITUTION',"

    "'DEPUTY_HEAD_OF_INSTITUTION',"

    "'CURRICULUM_COORDINATOR',"

    "'TEACHER',"

    "'ACCOUNTANT',"

    "'LIBRARIAN',"

    "'STORE_MANAGER',"

    "'WARDEN',"

    "'SECRETARY'"

)



STATUS_ENUM = "'PENDING_APPROVAL','APPROVED','REJECTED'"





def apply_mysql_enums(apps, schema_editor):

    if schema_editor.connection.vendor != "mysql":

        return

    with schema_editor.connection.cursor() as cursor:

        cursor.execute(

            f"""

            ALTER TABLE employees_employee

            MODIFY COLUMN role ENUM({ROLE_ENUM}) NOT NULL DEFAULT 'EMPLOYEE',

            MODIFY COLUMN approval_status ENUM({STATUS_ENUM})

                NOT NULL DEFAULT 'PENDING_APPROVAL'

            """

        )





def revert_mysql_enums(apps, schema_editor):

    if schema_editor.connection.vendor != "mysql":

        return

    with schema_editor.connection.cursor() as cursor:

        cursor.execute(

            """

            ALTER TABLE employees_employee

            MODIFY COLUMN role VARCHAR(32) NOT NULL DEFAULT 'EMPLOYEE',

            MODIFY COLUMN approval_status VARCHAR(20)

                NOT NULL DEFAULT 'PENDING_APPROVAL'

            """

        )





class Migration(migrations.Migration):



    dependencies = [

        ("employees", "0003_alter_employee_role"),

    ]



    operations = [

        migrations.RunPython(apply_mysql_enums, revert_mysql_enums),

    ]


