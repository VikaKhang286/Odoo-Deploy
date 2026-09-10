from odoo import fields, models, api
import logging

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    _description = 'Alert Tag'

    background_color = fields.Char(string="Màu background")
    navbar_background_color = fields.Char(string="Màu thanh Navigationbar")
    navbar_text_color = fields.Char(string="Màu chữ trên thanh navigationbar")
    text_color = fields.Char(string="Màu chữ phần thân")
    button_color = fields.Char(string="Màu nút trên thanh navigationbar")
    icon_color = fields.Char(string="Màu icon")
    filter_color = fields.Char(string="Màu thanh tiêu đề đầu trang")
    title_color = fields.Char(string="Màu thanh tiêu đề mục")
    image_1024 = fields.Image(max_width=1024, max_height=1024, readonly=False)
    image_logo_homepage_1024 = fields.Image(
        max_width=1024, max_height=1024, readonly=False)
    image_logo_homepage_64 = fields.Image(
        compute='_compute_logo_64',
        max_width=64, max_height=64, readonly=False)
    website_title = fields.Char(string="Website title")
    buble_color = fields.Char(string="Màu bong bóng")
    drop_background_color = fields.Char(string="Màu nền menu item")
    drop_text_color = fields.Char(string="Màu chữ menu item")

    sidebar_background = fields.Char(string="Màu nền side bar")
    sidebar_chose_background = fields.Char(string="Màu nền sidebar đang chọn")
    sidebar_text = fields.Char(string="Màu chữ side bar")
    search_color = fields.Char(string="Màu thanh tìm kiếm")

    website_background_color = fields.Char(string="Màu nền website")

    list_text_title = fields.Char(string="Màu nền list text title")
    list_title = fields.Char(string="Màu thanh tiêu đề list")
    list_table = fields.Char(string="Màu list table")
    list_text_table = fields.Char(string="Màu text list table")

    kanban_form = fields.Char(string="Màu form các mục kanban")
    kanban_background = fields.Char(string="Màu nền kanban")
    kanban_text = fields.Char(string="Màu chữ kanban")
    kanban_item = fields.Char(string="Màu chi tiết item kanban")

    discuss_background = fields.Char(string="Màu nền discuss")
    discuss_chose_sidebar = fields.Char(string="Màu hover sidebar discuss")

    def _compute_logo_64(self):
        for record in self:
            if record.image_logo_homepage_1024:
                record.image_logo_homepage_64 = record.image_logo_homepage_1024
            else:
                record.image_logo_homepage_64 = None

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        IPC = self.env['ir.config_parameter'].sudo()

        navbar_background_color = IPC.get_param(
            'change_odoo_theme_header_color.navbar_background_color')
        navbar_text_color = IPC.get_param(
            'change_odoo_theme_header_color.navbar_text_color')
        text_color = IPC.get_param('change_odoo_theme_header_color.text_color')
        button_color = IPC.get_param(
            'change_odoo_theme_header_color.button_color')
        icon_color = IPC.get_param('change_odoo_theme_header_color.icon_color')
        filter_color = IPC.get_param(
            'change_odoo_theme_header_color.filter_color')
        title_color = IPC.get_param(
            'change_odoo_theme_header_color.title_color')
        image_1024 = IPC.get_param('change_odoo_theme_header_color.image_1024')
        image_logo_homepage_64 = IPC.get_param(
            'change_odoo_theme_header_color.image_logo_homepage_64')
        image_logo_homepage_1024 = IPC.get_param(
            'change_odoo_theme_header_color.image_logo_homepage_1024')
        website_title = IPC.get_param(
            'change_odoo_theme_header_color.website_title')
        background_color = IPC.get_param(
            'change_odoo_theme_header_color.background_color')
        buble_color = IPC.get_param(
            'change_odoo_theme_header_color.buble_color')
        drop_background_color = IPC.get_param(
            'change_odoo_theme_header_color.drop_background_color')
        drop_text_color = IPC.get_param(
            'change_odoo_theme_header_color.drop_text_color')

        sidebar_background = IPC.get_param(
            'change_odoo_theme_header_color.sidebar_background')
        sidebar_chose_background = IPC.get_param(
            'change_odoo_theme_header_color.sidebar_chose_background')
        sidebar_text = IPC.get_param(
            'change_odoo_theme_header_color.sidebar_text')
        search_color = IPC.get_param(
            'change_odoo_theme_header_color.search_color')

        website_background_color = IPC.get_param(
            'change_odoo_theme_header_color.website_background_color')

        list_text_title = IPC.get_param(
            'change_odoo_theme_header_color.list_text_title')
        list_title = IPC.get_param('change_odoo_theme_header_color.list_title')
        list_table = IPC.get_param('change_odoo_theme_header_color.list_table')
        list_text_table = IPC.get_param(
            'change_odoo_theme_header_color.list_text_table')

        kanban_form = IPC.get_param(
            'change_odoo_theme_header_color.kanban_form')
        kanban_background = IPC.get_param(
            'change_odoo_theme_header_color.kanban_background')
        kanban_text = IPC.get_param(
            'change_odoo_theme_header_color.kanban_text')
        kanban_item = IPC.get_param(
            'change_odoo_theme_header_color.kanban_item')

        discuss_background = IPC.get_param(
            'change_odoo_theme_header_color.discuss_background')
        discuss_chose_sidebar = IPC.get_param(
            'change_odoo_theme_header_color.discuss_chose_sidebar')

        res.update(
            navbar_background_color=navbar_background_color,
            navbar_text_color=navbar_text_color,
            text_color=text_color,
            button_color=button_color,
            icon_color=icon_color,
            filter_color=filter_color,
            title_color=title_color,
            image_1024=image_1024,
            image_logo_homepage_1024=image_logo_homepage_1024,
            image_logo_homepage_64=image_logo_homepage_64,
            website_title=website_title,
            background_color=background_color,
            buble_color=buble_color,
            drop_background_color=drop_background_color,
            drop_text_color=drop_text_color,

            sidebar_background=sidebar_background,
            sidebar_chose_background=sidebar_chose_background,
            sidebar_text=sidebar_text,

            search_color=search_color,

            website_background_color=website_background_color,

            list_text_title=list_text_title,
            list_title=list_title,
            list_table=list_table,
            list_text_table=list_text_table,

            kanban_form=kanban_form,
            kanban_background=kanban_background,
            kanban_text=kanban_text,
            kanban_item=kanban_item,

            discuss_background=discuss_background,
            discuss_chose_sidebar=discuss_chose_sidebar,
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        IPC = self.env['ir.config_parameter'].sudo()
        IPC.set_param('change_odoo_theme_header_color.navbar_background_color',
                      self.navbar_background_color)
        IPC.set_param(
            'change_odoo_theme_header_color.navbar_text_color', self.navbar_text_color)
        IPC.set_param(
            'change_odoo_theme_header_color.text_color', self.text_color)
        IPC.set_param(
            'change_odoo_theme_header_color.button_color', self.button_color)
        IPC.set_param(
            'change_odoo_theme_header_color.icon_color', self.icon_color)
        IPC.set_param(
            'change_odoo_theme_header_color.filter_color', self.filter_color)
        IPC.set_param(
            'change_odoo_theme_header_color.title_color', self.title_color)
        IPC.set_param(
            'change_odoo_theme_header_color.image_1024', self.image_1024)
        IPC.set_param('change_odoo_theme_header_color.image_logo_homepage_1024',
                      self.image_logo_homepage_1024)
        IPC.set_param(
            'change_odoo_theme_header_color.image_logo_homepage_64', self.image_logo_homepage_64)
        IPC.set_param(
            'change_odoo_theme_header_color.website_title', self.website_title)
        IPC.set_param(
            'change_odoo_theme_header_color.background_color', self.background_color)
        IPC.set_param(
            'change_odoo_theme_header_color.buble_color', self.buble_color)
        IPC.set_param(
            'change_odoo_theme_header_color.drop_background_color', self.drop_background_color)
        IPC.set_param(
            'change_odoo_theme_header_color.drop_text_color', self.drop_text_color)
        IPC.set_param(
            'change_odoo_theme_header_color.sidebar_background', self.sidebar_background)
        IPC.set_param('change_odoo_theme_header_color.sidebar_chose_background',
                      self.sidebar_chose_background)
        IPC.set_param(
            'change_odoo_theme_header_color.sidebar_text', self.sidebar_text)
        IPC.set_param(
            'change_odoo_theme_header_color.search_color', self.search_color)

        IPC.set_param('change_odoo_theme_header_color.website_background_color',
                      self.website_background_color)

        IPC.set_param(
            'change_odoo_theme_header_color.list_text_title', self.list_text_title)
        IPC.set_param(
            'change_odoo_theme_header_color.list_title', self.list_title)
        IPC.set_param(
            'change_odoo_theme_header_color.list_table', self.list_table)
        IPC.set_param(
            'change_odoo_theme_header_color.list_text_table', self.list_text_table)

        IPC.set_param(
            'change_odoo_theme_header_color.kanban_form', self.kanban_form)
        IPC.set_param(
            'change_odoo_theme_header_color.kanban_background', self.kanban_background)
        IPC.set_param(
            'change_odoo_theme_header_color.kanban_text', self.kanban_text)
        IPC.set_param(
            'change_odoo_theme_header_color.kanban_item', self.kanban_item)

        IPC.set_param(
            'change_odoo_theme_header_color.discuss_background', self.discuss_background)
        IPC.set_param(
            'change_odoo_theme_header_color.discuss_chose_sidebar', self.discuss_chose_sidebar)

        # param = self.env['ir.config_parameter'].sudo()
        # param.set_param('hello_world.font_family', self.font_family)
