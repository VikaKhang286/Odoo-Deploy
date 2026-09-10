from odoo import models, fields, api

class HomeMenu(models.Model):
    _name = 'home.menu'
    _description = 'Home Menu'
    _rec_name = 'name'
    
    name = fields.Char(string='Tên', default='Trang chủ', required=True)