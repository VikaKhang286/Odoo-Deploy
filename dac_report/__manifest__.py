{
    # Tên module
    'name': 'DAC ERP Dashboard Report',
    'version': '1.0',
    
    # Loại module
    'category': '1. Duy An ERP',
    
    # Tên tác giả
    'author': 'Huỳnh Quốc An',
    
    # Độ ưu tiên module trong list module
    # Số càng nhỏ, độ ưu tiên càng cao
    #### Chấp nhận số âm
    'sequence': -1,
    
    # Mô tả module
    'summary': 'Module này để hiện báo cáo doanh thu bán hàng của Duy An Company',
    'description': '',
    
    # Module dựa trên các category nào
    # Khi hoạt động, category trong 'depends' phải được install
    ### rồi module này mới đc install
    'depends': ['base','web','dac_erp','CRM_DAC','sale','account','sale_management','product'],


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
        'views/action.xml',
        # Bật lên khi dùng mục tiêu theo tháng:
        'views/sales_goal_views.xml',
        'views/menuitem.xml',
    ],

    # Import các file cấu hình (chỉ gọi từ folder 'static')
    # Những file liên quan đến
    ## + các class mà hệ thống sử dụng
    ## + các chỉnh sửa giao diện
    ## + t
    'assets': {  
        'web.assets_backend': [
            'dac_report/static/src/js/**/*',
            'dac_report/static/src/xml/**/*',
            'dac_report/static/src/css/**/*',

        ],
    },
    'license': 'LGPL-3',
    
}