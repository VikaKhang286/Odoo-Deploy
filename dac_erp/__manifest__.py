{
    # Tên module
    'name': 'DAC ERP',
    'version': '8.0',
    
    # Loại module
    'category': '1. Duy An ERP',
    
    # Tên tác giả
    'author': 'Huỳnh Quốc An',
    
    # Độ ưu tiên module trong list module
    # Số càng nhỏ, độ ưu tiên càng cao
    #### Chấp nhận số âm
    'sequence': -1,
    
    # Mô tả module
    'summary': 'Module này để quản lý hệ thống ERP của Duy An Company',
    'description': '',
    
    # Module dựa trên các category nào
    # Khi hoạt động, category trong 'depends' phải được install
    ### rồi module này mới đc install
    'depends': ['base','web','home_menu','Chameleon','sale','sale_management','account','product','hr'],


    # Module có được phép install hay không
    # Nếu bạn thắc mắc nếu tắt thì làm sao để install
    # Bạn có thể dùng 'auto_install'
    'installable': True,
    'auto_install': False,
    'application': True,
    
    # Import các file cấu hình
    # Những file ảnh hưởng trực tiếp đến giao diện (không phải file để chỉnh sửa giao diện)
    ## hoặc hệ thống (file group, phân quyền)
    'data': [
        'security/user_access.xml',
        'security/ir.model.access.csv',
        'security/sale_order_access_rules.xml',
        'security/account_access_rules.xml',
        'security/dac_work_task_access_rules.xml',
        'data/currency_data.xml',
        'data/sale_order_accessory_data.xml',
        'data/cart_dimension_data.xml',
        'data/cart_dimension_standard_data.xml',
        'data/material_data.xml',
        'data/product_category_data.xml',
        'views/material_views.xml',
        'data/mail_activity_type_data.xml',
        'data/cron_data.xml',
        'data/openclaw_task_cron.xml',
        'data/openclaw_user_mapping_seed.xml',
        'data/ai_summary_server_actions.xml',
        'views/action_dashboard.xml',
        'views/cart_dimension_views.xml',
        'views/sale_order_view.xml',
        'views/sale_order_ui_simplify_view.xml',
        'views/sale_order_design_view.xml',
        'views/deposit_confirm_wizard_view.xml',
        'views/final_payment_confirm_wizard_view.xml',
        'views/no_deposit_confirm_wizard_view.xml',
        'views/production_deadline_wizard_view.xml',
        'views/delivery_address_wizard_view.xml',
        'views/production_not_done_warning_wizard_view.xml',
        'views/res_config_settings_views.xml',
        'views/account_move_deposit_view.xml',
        'views/account_move_view.xml',
        'views/account_payment_view.xml',
        'views/res_partner_views.xml',
        'views/res_users_views.xml',
        'views/hr_employee_views.xml',
        'views/product_views.xml',
        'views/dac_task_dashboard_views.xml',
        'views/dac_work_task_views.xml',
        'views/dac_quick_task_wizard_view.xml',
        'views/dac_openclaw_user_mapping_views.xml',
        'views/login_version_view.xml',
        'views/menuitem.xml',
        'report/account_report_invoice_inherit.xml',
    ],

    # Import các file cấu hình (chỉ gọi từ folder 'static')
    # Những file liên quan đến
    ## + các class mà hệ thống sử dụng
    ## + các chỉnh sửa giao diện
    ## + t
    'assets': {  
        'web.assets_backend': [
            'dac_erp/static/src/css/**/*',
            'dac_erp/static/src/css/backend/sale_order_form.css',
            'dac_erp/static/src/js/**/*',
            'dac_erp/static/src/xml/**/*',
        ],
        'web.assets_web': [
            'dac_erp/static/src/css/**/*',
            'dac_erp/static/src/css/backend/sale_order_form.css',
            'dac_erp/static/src/js/**/*',
            'dac_erp/static/src/xml/**/*',
        ],
    },
    'license': 'LGPL-3',
    
}
