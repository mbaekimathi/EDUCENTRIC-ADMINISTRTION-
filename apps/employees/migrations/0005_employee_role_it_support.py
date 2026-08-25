from django.db import migrations, models





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

    "'SECRETARY',"

    "'IT_SUPPORT'"

)





def apply_it_support_enum(apps, schema_editor):

    if schema_editor.connection.vendor != "mysql":

        return

    with schema_editor.connection.cursor() as cursor:

        cursor.execute(

            f"""

            ALTER TABLE employees_employee

            MODIFY COLUMN role ENUM({ROLE_ENUM}) NOT NULL DEFAULT 'EMPLOYEE'

            """

        )





def revert_it_support_enum(apps, schema_editor):

    if schema_editor.connection.vendor != "mysql":

        return

    previous = (

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

    with schema_editor.connection.cursor() as cursor:

        cursor.execute(

            f"""

            ALTER TABLE employees_employee

            MODIFY COLUMN role ENUM({previous}) NOT NULL DEFAULT 'EMPLOYEE'

            """

        )





class Migration(migrations.Migration):



    dependencies = [

        ("employees", "0004_role_approval_status_mysql_enum"),

    ]



    operations = [

        migrations.AlterField(

            model_name="employee",

            name="role",

            field=models.CharField(

                choices=[

                    ("EMPLOYEE", "Employee"),

                    ("HEAD_OF_INSTITUTION", "Head of Institution"),

                    ("DEPUTY_HEAD_OF_INSTITUTION", "Deputy Head of Institution"),

                    ("CURRICULUM_COORDINATOR", "Curriculum Coordinator"),

                    ("TEACHER", "Teacher"),

                    ("ACCOUNTANT", "Accountant"),

                    ("LIBRARIAN", "Librarian"),

                    ("STORE_MANAGER", "Store Manager"),

                    ("WARDEN", "Warden"),

                    ("SECRETARY", "Secretary"),

                    ("IT_SUPPORT", "IT Support"),

                ],

                default="EMPLOYEE",

                max_length=32,

            ),

        ),

        migrations.RunPython(apply_it_support_enum, revert_it_support_enum),

    ]


