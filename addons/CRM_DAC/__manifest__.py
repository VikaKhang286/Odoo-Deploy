{
     # Tên module
    'name': 'DAC Project Extension',
    'version': '4.1',
    
    # Loại module
    'category': '1. Duy An ERP',
    
    # Tên tác giả
    'author': 'Huỳnh Quốc An',
    
    # Độ ưu tiên module trong list module
    # Số càng nhỏ, độ ưu tiên càng cao
    #### Chấp nhận số âm
    'sequence': 0,

    # Mô tả
    'summary': 'Module dùng để đồng bộ các cuộc hội thoại từ pancake và tính KPI của nhân viên',
    'description': '',
    
    # Module dựa trên các category nào
    # Khi hoạt động, category trong 'depends' phải được install
    ### rồi module này mới đc install
    'depends': ['base','web','dac_erp','home_menu'],
    
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
        'security/ir.model.access.csv',
        'security/user_access_rule.xml',
        'data/pancake_bulk_sync_preset_data.xml',
        'data/cron_pancake.xml',
        # Tách riêng views cho Pages và Conversations
        'views/page_fm_page_views.xml',                    # Quản lý Pages đã đồng bộ
        'views/page_fm_conversation_views.xml',            # Quản lý Conversations  
        'views/page_fm_tag_view.xml',                      # Quản lý Tag
        'views/page_fm_customer_views.xml',                # Pancake Customer aliases + partner tab
        'views/KPI_View.xml',
        'views/res_partner_views_inherit_pancake.xml',
        'views/res_users_views_inherit_pancake.xml',
        'views/sale_order_views_inherit_pancake.xml',
        'views/conversation_message_sync_wizard_views.xml',
        'views/create_order_wizard_views.xml',
        'views/partner_dedup_wizard_views.xml',            # Wizard gom khách trùng
        'views/pancake_bulk_sync_dashboard_views.xml',
        'views/pancake_dashboard_views.xml',
        'views/pancake_message_dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/pancake_status_visual_views.xml',
        'views/pancake_message_sync_job_views.xml',
        'views/pancake_staff_mapping_views.xml',
        'views/menuitem.xml',
    ],


    # Import các file cấu hình (chỉ gọi từ folder 'static')
    # Những file liên quan đến
    ## + các class mà hệ thống sử dụng
    ## + các chỉnh sửa giao diện
    ## + t
    'assets': {
        'web.assets_backend': [
            'CRM_DAC/static/src/scss/backend/pancake_dashboard.scss',
            'CRM_DAC/static/src/scss/backend/zzz_toggle_white.scss',
            'CRM_DAC/static/src/js/backend/pancake_bulk_sync_console.js',
            'CRM_DAC/static/src/xml/backend/pancake_bulk_sync_console.xml',
            'CRM_DAC/static/src/js/backend/pancake_many2one_field.js',
            'CRM_DAC/static/src/xml/backend/pancake_many2one_field.xml',
            'CRM_DAC/static/src/js/backend/create_order_list_view.js',
            'CRM_DAC/static/src/xml/backend/create_order_list_view.xml',
        ],
    },
    'license': 'LGPL-3',
}
