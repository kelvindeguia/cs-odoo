import logging
import pytz
import threading
import pandas as pd
import numpy as np
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from psycopg2 import sql

from odoo import api, fields, models, tools, SUPERUSER_ID
from odoo.addons.iap.tools import iap_tools
from odoo.addons.mail.tools import mail_validation
from odoo.addons.phone_validation.tools import phone_validation
from odoo.exceptions import UserError, AccessError
from odoo.osv import expression
from odoo.tools.translate import _ 
from odoo.tools import date_utils, email_re, email_split, is_html_empty, groupby
from odoo.tools.misc import get_lang
from random import randint
from odoo.exceptions import ValidationError

class CSPortal(models.Model):
    _name = 'cs.portal.main'
    _description = 'CS Portal Main'
    _rec_name = 'account_name'
    _inherit = ['mail.thread.cc',
               'mail.thread.main.attachment',
               'mail.thread.blacklist',
               'mail.activity.mixin',
               'utm.mixin']

    active = fields.Boolean(default=True)
    # For Currency
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', default=lambda self: self.env.user.company_id.currency_id.id)
    
    account_name = fields.Char('Account Name', store=True, required=True)
    account_status = fields.Selection([('active', 'Active'),
                                       ('inactive', 'Inactive'),
                                       ('sourcing', 'Sourcing')], 'Account Status', store=True)
    revenue_last_year = fields.Integer('Revenue Last Year', store=True)
    ytd_revenue = fields.Integer('YTD Revenue', store=True)
    expected_revenue = fields.Integer('Expected Revenue', store=True)
    likelihood_of_growth = fields.Char('Likelihood of Growth', store=True)
    company_domain = fields.Char('Company Domain', store=True)
    company_description = fields.Text('Company Description', store=True)
    industry = fields.Char('Industry', store=True)
    company_phone_number = fields.Char('Company Phone Number', store=True)
    city = fields.Char('City', store=True)
    state = fields.Char('State', store=True)
    year_founded = fields.Char('Year Founded', store=True)
    contract_expiration = fields.Date('Contract Expiration', store=True)
    primary_hr_poc = fields.Selection([('christian', 'Christian Reyes'),
                                       ('lyka', 'Lyka Cabungcag'),
                                       ('john', 'John Maverick Malabanan'),
                                       ('mindy', 'Mindy Andres')], 'Primary HR POC', store=True)
    ceo = fields.Char('CEO', store=True)
    number_of_employees = fields.Char('Number of Employees', store=True)
    publicly_traded = fields.Selection([('yes', 'Yes'), ('no', 'No')], 'Publicly Traded?', store=True)
    annual_sales_revenue = fields.Char('Annual Sales Revenue', store=True)
    date_line_fee = fields.Monetary('Date Line Fee', store=True)
    infrastructure_fee = fields.Monetary('Infrastructure Fee', store=True)
    mark_up_percentage = fields.Float('Mark Up Percentage', store=True, digits=(5, 2))
    year_started_with_isw = fields.Char('Year Started with iSW', store=True)
    isw_headcount = fields.Integer('iSW Headcount', store=True)
    isw_roles_position = fields.Text('iSW Roles/Position', store=True)
    other_notes = fields.Html('Other Notes', store=True)
    start_date = fields.Date('Client Start Date', store=True)
    stage_date = fields.Datetime('Stage Date', store=True, compute='_compute_difference')
    sales_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_sales_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Sales Handover File')
    
    # SALE PIPELINE STAGE SLA
    x_stage_sla = fields.Integer('Stage Aeging', compute="_compute_stage_ageing")
    x_stage_sla_total = fields.Integer('Stage Aeging Reference', store=True)
    x_date_today = fields.Datetime('Date Today', compute='_compute_date_today')
    x_stage_days_passed = fields.Selection([('less_than_10_days', 'Less than 10 days'), ('passed_10_days', 'Passed 10 days')], 'Days Passed', store=True)

    # SLA FIELDS
    ageing = fields.Integer('Ageing', compute='_compute_ageing')
    ageing_ref = fields.Integer('Ageing Reference', store=True)
    date_today = fields.Date('Date Today', compute='_compute_date_today')
    
    # ACCOUNT OWNER
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Account Owner', index=True)
    # SECONDARY OWNER
    secondary_owner_id = fields.Many2one('cs.portal.secondary.owner', string='Secondary Owner', index=True)
    # TAGS
    tag_ids = fields.Many2many('cs.portal.tag', string='Tags')
    # CONTRACT LENGTH
    contract_length_id = fields.Many2one('cs.portal.contract.length', string='Contract Length')
    # PRIMARY HR POC
    primary_hr_poc_id = fields.Many2one('cs.portal.primary.hr.poc', string='Primary HR POC')
    # SALES PIPELINE STAGES
    sales_pipeline_stage_id = fields.Many2one('cs.portal.sales.pipeline', string='Sales Pipeline Status', store=True, default='1', group_expand='_expand_sales_stages')
    # GENERAL PIPELINE STAGES
    general_pipeline_stage_id = fields.Many2one('cs.portal.general.pipeline', string='General Account Status', store=True, default='1', group_expand='_expand_stages')
    # SEPARATION STATUS
    separation_status_id = fields.Many2one('cs.portal.separation.status', string='Separation Status', store=True)
    # REASON FOR SEPARATION
    reason_for_separation_id = fields.Many2one('cs.portal.reason.for.separation', string='REASON For Separation (Resignation Letter/ Termination notice)', store=True)
    # POSITION
    position_id = fields.Many2one('cs.portal.position', string='Position', store=True)

    # Related Fields
    poc_information_ids = fields.One2many('cs.portal.poc.information', 'cs_portal_main_id', string='POC Information')
    projects_and_client_request_ids = fields.One2many('cs.portal.projects.and.client.request', 'cs_portal_main_id', string='Client Request')
    opportunities_ids = fields.One2many('cs.portal.opportunities', 'cs_portal_main_id', string='Revenue Opportunities')
    account_planning_ids = fields.One2many('cs.portal.account.planning', 'cs_portal_main_id', string='Account Planning')
    client_escalations_ids = fields.One2many('cs.portal.client.escalations', 'cs_portal_main_id', string='Client Escalations')
    csat_ids = fields.One2many('cs.portal.csat', 'cs_portal_main_id', string='CSAT')
    requisition_ids = fields.One2many('cs.portal.requisition', 'cs_portal_main_id', string='Requisition')
    client_interactions_ids = fields.One2many('cs.portal.client.interactions', 'cs_portal_main_id', string='Client Interactions')
    internal_interactions_ids = fields.One2many('cs.portal.internal.interactions', 'cs_portal_main_id', string='Internal Interactions')
    email_interactions_ids = fields.One2many('cs.portal.email.interactions', 'cs_portal_main_id', string='Email Interactions')
    hiring_interactions_ids = fields.One2many('cs.portal.hiring.interactions', 'cs_portal_main_id', string='Hiring Interactions')
    attrition_and_backfills_ids = fields.One2many('cs.portal.attrition.and.backfills', 'cs_portal_main_id', string='Attrition')
    master_file_ids = fields.One2many('cs.portal.master.file', 'cs_portal_main_id', string='Master File')
    growth_ids = fields.One2many('cs.portal.growth', 'cs_portal_main_id', string='Growth 2')
    rect_to_cs_target_ids = fields.One2many('cs.portal.rect.to.cs.target', 'cs_portal_main_id', string='Rect to CS Target')
    active_clients_ids = fields.One2many('cs.portal.active.clients', 'cs_portal_main_id', string='Active Clients')
    overall_ids = fields.One2many('cs.portal.overall', 'cs_portal_main_id', string='Overall')
    
    date_closed = fields.Date('Date Closed', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    category_id = fields.Many2one('cs.portal.projects.and.client.request.category', string='Category')
    email = fields.Char('Email', store=True)
    number = fields.Char('Number', store=True)
    client_name = fields.Char('Client Name', store=True)
    priority = fields.Selection([('urgent', 'Urgent'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')], 'Priority', store=True)
    testField = fields.Char('Test Field', store=True)

    # Record URL
    account_url = fields.Text(string='Account URL', compute="_compute_url")

    def _compute_url(self):
        # menu_id = self._context.get('menu_id', False)
        # base_url = self.env['ir.config_parameter'].get_param('web.base.url')
        base_url = 'https://cs17.isw-hub.com/web#id=%d&cids=1&menu_id=394&action=561&model=%s&view_type=form' % (self.id, self._name)
        # base_url = 'http://10.2.1.26:8070/web#id=%d&cids=1&menu_id=182&action=290&model=%s&view_type=form' % (
        # self.id, self._name)
        self.account_url = base_url

    @api.depends('sales_pipeline_stage_id')
    def _compute_difference(self):
        for rec in self:
            if rec.sales_pipeline_stage_id:
                rec.stage_date = datetime.today()

    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = date.today()
        self.x_date_today = datetime.today()

    def _compute_ageing(self):
        for rec in self:
            if rec.start_date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.start_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = -1
                initial_date = rec.start_date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.ageing = working_days
                rec.ageing_ref = rec.ageing
            else:
                rec.ageing = False   

    # Stage Ageing Computation
    def _compute_stage_ageing(self):
        for rec in self:
            if rec.stage_date and rec.x_date_today:
                # Calculate the age in days
                age_timedelta = rec.x_date_today - rec.stage_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = -1
                initial_date = rec.stage_date

                while initial_date <= rec.x_date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.x_stage_sla = working_days
                rec.x_stage_sla_total = rec.x_stage_sla
            else:
                rec.x_stage_sla = False 
    
    @api.constrains('start_date')
    def _start_date_validation(self):
        for record in self:
            # Set the user's time zone
            user_timezone = pytz.timezone('Asia/Singapore')

            # Get the current date and time in the user's time zone
            user_time = datetime.now(user_timezone)
            
            # Extract the date component from user_time
            user_date = user_time.date()
            if record.start_date and record.start_date > user_date:
                raise ValidationError("You can't set the client start date on a future date.")

    @api.model
    def _expand_stages(self, stages, domain, order):
        stages = self.env['cs.portal.general.pipeline'].search([])  # Retrieve recordset
        return stages
    
    def _expand_sales_stages(self, stages, domain, order):
        stages = self.env['cs.portal.sales.pipeline'].search([])  # Retrieve recordset
        return stages

class CSPortal_Account_Owner(models.Model):
    _name = 'cs.portal.account.owner'
    _description = 'Account Owner'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Account Owner', store=True, required=True)
    account_owner_ids = fields.Many2one('res.users', string='Account Owner Reference', store=True)
    user_id = fields.Integer('User ID Reference', store=True, related='account_owner_ids.id')
    active_account_owner = fields.Boolean('Account Owner Status', store=True)
    email_address = fields.Char('Email Address', store=True, related='account_owner_ids.login')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Account Owner already exists!'),
    ]

class CSPortal_Secondary_Owner(models.Model):
    _name = 'cs.portal.secondary.owner'
    _description = 'Secondary Owner'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Secondary Owner', store=True, required=True)
    account_owner_ids = fields.Many2one('res.users', string='Account Owner Reference', store=True)
    user_id = fields.Integer('User ID Reference', store=True, related='account_owner_ids.id')
    active_secondary_owner = fields.Boolean('Secondary Owner Status', store=True)
    email_address = fields.Char('Email Address', store=True, related='account_owner_ids.login')

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Secondary Owner already exists!'),
    ]

class CSPortal_Tag(models.Model):
    _name = 'cs.portal.tag'
    _description = 'CS Portal Tag'
    _rec_name = 'name'

    def _get_default_color(self):
        return randint(1, 11)

    active = fields.Boolean(default=True)
    name = fields.Char('Tag Name', required=True, translate=True)
    color = fields.Integer('Color', default=_get_default_color)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Tag name already exists!'),
    ]

class CSPortal_Contract_Length(models.Model):
    _name = 'cs.portal.contract.length'
    _description = 'Contract Length'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Contract Length', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Contract Length already exists!'),
    ]

class CSPortal_Primary_HR_POC(models.Model):
    _name = 'cs.portal.primary.hr.poc'
    _description = 'Primary HR POC'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Primay HR POC', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Primary HR POC already exists!'),
    ]

class CSPortal_POC_Information(models.Model):
    _name = 'cs.portal.poc.information'
    _description = 'CS Portal POC Information'
    _rec_name = 'name'

    active = fields.Boolean(default=True)

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    name = fields.Char('Name', store=True, required=True)
    email = fields.Char('Email', store=True)
    number = fields.Char('Number', store=True)
    position_job_title = fields.Char('Position/Job Title', store=True)
    buyer = fields.Boolean('Buyer', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Owner', index=True)
    client_satisfaction = fields.Selection([('detractors', 'Detractors'),
                                            ('promoters', 'Promoters'),], 'Client Satisfaction', store=True)
    
class CSPortal_Projects_and_Client_Request(models.Model):
    _name = 'cs.portal.projects.and.client.request'
    _description = 'CS Portal Projects and Client Request'
    _rec_name = 'subject'

    active = fields.Boolean(default=True)

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_opened = fields.Datetime('Date Opened', store=True)
    subject = fields.Char('Subject', store=True, required=True)
    client_name = fields.Char('Client Name', store=True)
    client_id = fields.Many2one('cs.portal.poc.information', string='Client POC', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM')
    category_id = fields.Many2one('cs.portal.projects.and.client.request.category', string='Category')
    status = fields.Selection([('new', 'New'),
                               ('ongoing', 'Ongoing'),
                               ('on_hold', 'On Hold'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True)
    date_closed = fields.Datetime('Date Closed', store=True)
    details = fields.Html('Details', store=True)
    projects_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_projects_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    # deliverables = fields.Text('Client Interaction Deliverables', store=True, required=True)
    # interaction_id = fields.Many2one('cs.portal.client.interactions', 'Client Interaction')   

class CSPortal_Projects_Category(models.Model):
    _name = 'cs.portal.projects.and.client.request.category'
    _description = 'Projects and Client Request Category'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Category', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Category already exists!'),
    ]

class CSPortal_Opportunities(models.Model):
    _name = 'cs.portal.opportunities'
    _description = 'CS Portal Opportunities'
    _rec_name = 'subject'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_created = fields.Datetime('Date Created', store=True)
    subject = fields.Char('Subject', store=True, required=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    client_name = fields.Char('Client Name', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM')
    details = fields.Html('Details', store=True)

class CSPortal_Client_Escalations(models.Model):
    _name = 'cs.portal.client.escalations'
    _description = 'CS Portal Client Escalations'
    _rec_name = 'client_name'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_opened = fields.Datetime('Date Opened', store=True)
    client_name = fields.Char('Client Name', store=True, required=True)
    participants = fields.Char('Participants', store=True)
    department = fields.Selection([('client_services', 'Client Services'),
                                   ('human_resources', 'Human Resources'),
                                   ('it', 'IT'),
                                   ('finance', 'Finance'),
                                   ('facilities', 'Facilities')], 'Department', store=True)
    reason = fields.Text('Reason', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    date_closed = fields.Datetime('Date Closed', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM')
    description = fields.Html('Description', store=True)
    client_escalations_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_client_escalation_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')

class CSPortal_CSAT(models.Model):
    _name = 'cs.portal.csat'
    _description = 'CS Portal CSAT'
    _rec_name = 'subject'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_submitted = fields.Datetime('Date Submitted', store=True)
    subject = fields.Char('Subject', store=True, required=True)
    submitted_by = fields.Char('Submitted By', store=True)
    # client_name = fields.Char('Client Name', store=True) requested to remove by sir oliver
    satisfaction_rating = fields.Selection([('poor', 'Poor'),
                                            ('average', 'Average'),
                                            ('good', 'Good'),
                                            ('very_good', 'Very Good'),
                                            ('excellent', 'Excellent')], 'Satisfaction Rating', store=True)
    details = fields.Html('Details', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM')
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    csat_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_csat_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    
class CSPortal_Requisition(models.Model):
    _name = 'cs.portal.requisition'
    _description = 'CS Portal Requisition'
    _rec_name = 'id'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_opened = fields.Datetime('Date Opened', store=True)
    req_id = fields.Char('Requisition ID', store=True)
    # growth = fields.Integer('Growth', store=True, required=True)
    position_classification = fields.Selection([('growth', 'Growth'), ('backfill', 'Backfill')], 'Position Classification', store=True)
    backfill = fields.Integer('Backfill', store=True)
    headcount = fields.Integer('Headcount', store=True)
    job_title_role = fields.Char('Job Title/Role', store=True)
    # account_owner_id = fields.Many2one('cs.portal.account.owner', string='Owner')
    req_status = fields.Selection([('for calibration', 'For Calibration'),
                               ('open', 'Open'),
                               ('reopened', 'Reopened'),
                               ('ongoing sourcing', 'Ongoing Sourcing'),
                               ('on hold', 'On Hold'),
                               ('cancelled', 'Cancelled'),
                               ('filled', 'Filled'),
                               ('completed', 'Completed'),
                               ('waiting_for_client', 'Waiting for Client'),], 'Status', store=True, default='open')
    salary_range_budget = fields.Char('Salary Range/Budget', store=True)
    existing_roles_id = fields.Many2one('cs.portal.requisition.existing.roles', 'Existing Roles')
    date_closed = fields.Datetime('Date Closed', store=True)
    remarks = fields.Text('Remarks', store=True)
    requisition_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_requisition_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    
class CSPortal_Requisition_Existing_Roles(models.Model):
    _name = 'cs.portal.requisition.existing.roles'
    _description = 'CS Portal Requisition Existing Roles'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Existing Roles', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Existing Roles already exists!'),
    ]

class CSPortal_Client_Interactions(models.Model):
    _name = 'cs.portal.client.interactions'
    _description = 'CS Portal Client Interactions'
    _rec_name = 'id'
    _inherit = ['mail.thread.cc',
               'mail.activity.mixin',
               'utm.mixin']

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date = fields.Datetime('Date', store=True)
    deliverables = fields.Text('Deliverables', store=True)
    participants = fields.Char('Participants', store=True)
    type_of_interactions_id = fields.Many2one('cs.portal.client.interactions.type', 'Type of Interactions', store=True)
    interactions_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_interactions_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    details = fields.Html('Details', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True)
    
    #For Escalation trigger#
    escalation = fields.Boolean('For Escalation?', store=True)

    #Email reminder trigger#
    reminder = fields.Boolean('Task Reminder for Account Owner', store=True)
    task_reminder = fields.Boolean('Task Reminder for Both Account Owners', store=True)
    date_today = fields.Datetime('Datetime Today', compute='_compute_date_today')
    task_ageing = fields.Integer('Task Ageing', compute="_compute_task_ageing")
    task_ageing_total = fields.Integer('Task Ageing Reference')

    # For Reminder Days Configurations
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    # Task Ageing Computation
    def _compute_task_ageing(self):
        for rec in self:
            if rec.date and rec.date_today:
                # Calculate the age in days
                age_timedelta = rec.date_today - rec.create_date

                # Calculate the number of working days (excluding weekends)
                total_days = age_timedelta.days
                working_days = -1
                initial_date = rec.date

                while initial_date <= rec.date_today:
                    if initial_date.weekday() < 5:  # Monday to Friday (0 to 4)
                        working_days += 1
                    initial_date += timedelta(days=1)

                rec.task_ageing = working_days
                rec.task_ageing_total = rec.task_ageing
            else:
                rec.task_ageing = False 
    
    @api.onchange('escalation')
    def _onchange_escalation(self):
        for record in self:
            client_escalation = self.env['cs.portal.client.escalations'].create({
                    'client_name': record.cs_portal_main_id.account_name,
                    'description': record.details,
                    'date_opened': record.date,
                    'cs_portal_main_id': record._origin.cs_portal_main_id.id,
                    'status': record.status,
                    'participants': record.participants
                })
    
    @api.model
    def create(self, values):
        record = super(CSPortal_Client_Interactions, self).create(values)
        if record.deliverables:
            project_request = self.env['cs.portal.projects.and.client.request'].create({
                'subject': "New Project Request",
                'details': "New project request created with deliverables: %s" % (record.deliverables),
                'active': True
            })
        return record 
    
    # @api.multi
    # def action_add_client_interactions_line(self):
    #     self.create({
    #         'cs_portal_main_id': self.env.context.get('default_cs_portal_main_id', False),
    #         'date': fields.Date.today(),
    #         'deliverables': 'Default Deliverables',  # You can customize default values here
    #         'participants': 'Default Participants',
    #         'type_of_interactions_id': self.env.context.get('default_type_of_interactions_id', False),
    #         'details': 'Default Details',
    #         'status': 'new'
    #     })
    #     return True

class CSPortal_Client_Interactions_Type(models.Model):
    _name = 'cs.portal.client.interactions.type'
    _description = 'CS Portal Client Interactions Type of Interactions'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Type of Interactions', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Type of Interactions already exists!'),
    ]

class CSPortal_Internal_Interactions(models.Model):
    _name = 'cs.portal.internal.interactions'
    _description = 'CS Portal Internal Interactions'
    _rec_name = 'id'
    
    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date = fields.Date('Date', store=True)
    deliverables = fields.Text('Deliverables', store=True)
    participants = fields.Char('Participants', store=True)
    type_of_interactions_id = fields.Many2one('cs.portal.internal.interactions.type', 'Type of Interactions')
    internal_interactions_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_internal_interactions_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    start_time = fields.Datetime('Start Time', store=True)
    end_time = fields.Datetime('End Time', store=True)
    details = fields.Html('Details', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')


class CSPortal_Internal_Interactions_Type(models.Model):
    _name = 'cs.portal.internal.interactions.type'
    _description = 'CS Portal Internal Interactions Type of Interactions'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Type of Interactions', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Type of Interactions already exists!'),
    ]

class CSPortal_Email_Interactions(models.Model):
    _name = 'cs.portal.email.interactions'
    _description = 'CS Portal Email Interactions'
    _rec_name = 'id'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date = fields.Date('Date', store=True)
    deliverables = fields.Text('Deliverables', store=True, required=True)
    participants = fields.Char('Participants', store=True)
    type_of_interactions_id = fields.Many2one('cs.portal.email.interactions.type', 'Type of Interactions')
    email_interactions_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_email_interactions_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    details = fields.Html('Details', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    
class CSPortal_Hiring_Interactions(models.Model):
    _name = 'cs.portal.hiring.interactions'
    _description = 'CS Portal Hiring Interactions'
    _rec_name = 'id'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date = fields.Date('Date', store=True)
    deliverables = fields.Text('Deliverables', store=True)
    participants = fields.Char('Participants', store=True)
    type_of_interactions_id = fields.Many2one('cs.portal.hiring.interactions.type', 'Type of Interactions')
    hiring_interactions_attachment_ids = fields.Many2many(comodel_name='ir.attachment',
                                           relation='m2m_ir_hiring_interactions_attachment_rel',
                                           column1='m2m_id',
                                           column2='attachment_id',
                                           string='Attachments')
    details = fields.Html('Details', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')

class CSPortal_Hiring_Interactions_Type(models.Model):
    _name = 'cs.portal.hiring.interactions.type'
    _description = 'CS Portal Hiring Interactions Type of Interactions'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Type of Interactions', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Type of Interactions already exists!'),
    ]

class CSPortal_Email_Interactions_Type(models.Model):
    _name = 'cs.portal.email.interactions.type'
    _description = 'CS Portal Email Interactions Type of Interactions'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Type of Interactions', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Type of Interactions already exists!'),
    ]

class CSPortal_Attrition_and_Backfills(models.Model):
    _name = 'cs.portal.attrition.and.backfills'
    _description = 'CS Portal Attrition and Backfills'
    _rec_name = 'employee_name'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    account_name = fields.Char('Account Name', store=True, required=True)
    employee_id = fields.Char('Employee ID', required=True, store=True)
    employee_name = fields.Char('Full Name', store=True, required=True)
    department = fields.Selection([('operations', 'OPERATIONS'), ('support', 'SUPPORT')], 'Department', store=True)
    position = fields.Char('Position', required=True, store=True)
    employment_status = fields.Selection([('regular', 'REGULAR'), ('probationary', 'PROBATIONARY')], 'Employment Status', store=True)
    date_hired = fields.Date('Date Hired', store=True)
    date_of_separation = fields.Date('Separation Date', store=True)
    separation_status_id = fields.Many2one('cs.portal.separation.status', string='Separation Status', store=True)
    category = fields.Selection([('authorized', 'Authorized'), ('desired', 'Desired'), ('undesired', 'Undesired')], 'Category', store=True)
    voluntary_involuntary = fields.Selection([('involuntary', 'INVOLUNTARY'), ('voluntary', 'VOLUNTARY')], 'Voluntary/Involuntary', store=True)
    reason_for_separation_id = fields.Many2one('cs.portal.reason.for.separation', string='Reason For Separation (Resignation Letter/ Termination notice)', store=True)

    # month = fields.Char('Month', compute='_compute_separation_month', store=True)
    month = fields.Char('Month', store=True)
    # year = fields.Char('Year', compute='_compute_separation_year', store=True)
    year = fields.Char('Year', store=True)
    # account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', compute='_compute_account_owner_id', index=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', store=True, index=True)
    # attrition_category = fields.Selection([('end_of_project', 'End of Project'),('involuntary', 'Involuntary'), ('voluntary', 'Voluntary')], 'Attrition Category', compute='_compute_attrition_category', store=True)
    attrition_category = fields.Selection([('end_of_project', 'End of Project'),('involuntary', 'Involuntary'), ('voluntary', 'Voluntary')], 'Attrition Category', store=True)
    # backfill_attrition = fields.Integer('Backfill Attrition', compute='_compute_backfill_attrition', store=True)
    backfill_attrition = fields.Integer('Backfill Attrition', store=True)
    # voluntary = fields.Integer('Voluntary', compute='_compute_voluntary', store=True)
    voluntary = fields.Integer('Voluntary', store=True)
    # involuntary = fields.Integer('Involuntary', compute='_compute_involuntary', store=True)
    involuntary = fields.Integer('Involuntary', store=True)
    # backfilled_hc = fields.Integer('Backfilled HC', compute='_compute_backfilled_hc', store=True)
    backfilled_hc = fields.Integer('Backfilled HC', store=True)

    # account_owner_id = fields.Many2one('cs.portal.account.owner', string='Client Service Manager', compute='_compute_account_owner_id', index=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Client Service Manager', store=True, index=True)
    init_client_approach_date = fields.Date('Initial Client Approach Date', store=True)
    backfills_confirmation = fields.Selection([('no', 'No'), ('not', 'Not Now'), ('redundancy/retrenched', 'Redundancy/Retrenched'), ('yes', 'Yes')], 'Client Agreed To Backfill?', store=True)
    initial_remarks = fields.Text('Initial Remarks', store=True)
    req_id = fields.Char('Requisition ID', store=True)
    progress_remarks = fields.Text('Progress Remarks', store=True)
    backfill_req_date = fields.Date('Odoo Backfill Requisition Date', store=True)
    backfill_ageing = fields.Char('Backfill Ageing', store=True)
    recruitment_action = fields.Selection([('awaiting_odoo_requisition', 'Awaiting Odoo Requsition'), ('backfill_not_granted', 'Backfill Not Granted'), ('filled', 'Filled'),
                                           ('for_further_discussion', 'For Further Discussion'), ('internal_promotion_made', 'Internal Promotion Made'), ('ongoing_interviews', 'Ongoing Interviews')],
                                           'Recruitment Action', store=True)
    filled_date = fields.Date('Field Date', store=True)
    recruitment_ageing = fields.Char('Recruitment Ageing', store=True)
    # client_response = fields.Selection([('yes', 'Yes'), ('no', 'No')], "Client's Confirmation", store=True)
    # client_reason = fields.Text("Client's Reason (Why they decline)", store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed')], 'Status', store=True)
    
    @api.depends('date_of_separation')
    def _compute_separation_month(self):
        for record in self:
            if record.date_of_separation:
                # Convert date to month name
                record.month = record.date_of_separation.strftime("%B")
            else:
                record.month = ''

    @api.depends('date_of_separation')
    def _compute_separation_year(self):
        for record in self:
            if record.date_of_separation:
                # Convert date to year
                record.year = record.date_of_separation.strftime("%Y")
            else:
                record.year = ''

    @api.depends('employee_name')
    def _compute_account_owner_id(self):
        for record in self:
            record.account_owner_id = record.cs_portal_main_id.account_owner_id

    @api.depends('separation_status_id')
    def _compute_attrition_category(self):
        for record in self:
            if record.separation_status_id.name == "End of Project":
                record.attrition_category = "end_of_project"
            else:
                record.attrition_category = record.voluntary_involuntary
    
    @api.depends('department', 'separation_status_id')
    def _compute_backfill_attrition(self):
        for record in self:
            department = record.department if record.department else ''
            separation_status = record.separation_status_id.name if record.separation_status_id else ''
            record.backfill_attrition = self._compute_backfill_attrition_value(department, separation_status)
    
    @staticmethod
    def _compute_backfill_attrition_value(department, separation_status_id):
        if department == 'support':
            return 0
        if separation_status_id == 'End of Project':
            return 1
        if separation_status_id == 'Redundate':
            return 0
        return 1
    
    @api.depends('department', 'attrition_category')
    def _compute_voluntary(self):
        for record in self:
            if record.department == 'support':
                record.voluntary = 0
            elif record.attrition_category == 'voluntary':
                record.voluntary = 1
            else:
                record.voluntary = 0

    @api.depends('attrition_category')
    def _compute_involuntary(self):
        for record in self:
            if record.attrition_category == 'involuntary':
                record.involuntary = 1
            else:
                record.involuntary = 0
    
    @api.depends('month', 'year')
    def _compute_backfilled_hc(self):
        for record in self:
            domain = [
                ('month', '=', record.month),
                ('year', '=', record.year),
                ('req_position_classification', '=', 'backfill')
            ]
            backfills = self.env['cs.portal.growth'].search(domain)
            record.backfilled_hc = sum(backfill.backfill for backfill in backfills)


# Relationship Map Start ###
class CSPortal_Relationship_Map(models.Model):
    _name = 'cs.portal.relationship.map'
    _description = 'CS Relationship Map'
    _rec_name = 'x_client_name_id'

    x_client_name_id = fields.Char('Client Name', store=True)

### RAW start ###
class CSPortal_Raw(models.Model):
    _name = 'cs.portal.raw'
    _description = 'CS Raw'
    _rec_name = 'x_account'

    x_account = fields.Char('Account', store=True, required=True)
    x_client_name_id = fields.Char('Client Name', store=True)
    x_position = fields.Char('Position', store=True)
    account_accountable_id = fields.Many2many('cs.portal.accountable', string='Accountable', index=True)
    x_decision_maker = fields.Selection([('decision maker', 'Decision Maker'), ('influencer', 'Influencer')], 'Decision Maker/Influencer', store=True)
    x_status = fields.Selection([('positive', 'Positive'), ('neutral', 'Neutral'), ('detractor', 'Detractor')], 'Status', store=True)
    x_account_type = fields.Text('Key/Non-key Account', store=True)
    x_revenue = fields.Char('Revenue', store=True)
    x_space_type = fields.Selection([('n/a', 'N/A'), ('white', 'White'), ('black', 'Black')], 'White/Black Space', store=True)

    #account owner stored data
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Account Owner', index=True)
    #convert many2one to char
    account_owner_id_str = fields.Char('Account Owner', store=True, default='', compute="_compute_x_account_owner_id_str")
    
    #secondary owner stored data
    secondary_owner_id = fields.Many2one('cs.portal.secondary.owner', string='Secondary Owner')
    #convert many2one to char
    secondary_owner_id_str = fields.Char('Secondary Owner', store=True, default='', compute="_compute_x_secondary_owner_id_str")

    x_buyer = fields.Selection([('y', 'Y'), ('n', 'N')], 'Buyer', store=True)
    x_ap_responsibility = fields.Selection([('y', 'Y'), ('n', 'N')], 'AP Responsibility', store=True)
    x_comments = fields.Char('Comments', store=True)
    x_clients_birthday = fields.Date('Clients Birthday', store=True)
    #x_clients_birthday_str new field
    x_clients_birthday_str = fields.Char('Clients Birthday', store=True, default='', compute="_compute_x_clients_birthday_str")

    @api.depends('account_owner_id')
    def _compute_x_account_owner_id_str(self):
        for rec in self:
            account_owner_value = rec.account_owner_id
            if rec.account_owner_id:
                rec.account_owner_id_str = str(rec.account_owner_id.name)
            else:
                rec.account_owner_id_str = ''

    @api.depends('secondary_owner_id')
    def _compute_x_secondary_owner_id_str(self):
        for rec in self:
            secondary_owner_value = rec.account_owner_id
            if rec.secondary_owner_id:
                rec.secondary_owner_id_str = str(rec.secondary_owner_id.name)
            else:
                rec.secondary_owner_id_str = ''

    @api.depends('x_clients_birthday')
    def _compute_x_clients_birthday_str(self):
        for rec in self:
            clients_date_value = rec.x_clients_birthday
            if rec.x_clients_birthday:
                rec.x_clients_birthday_str = ""
                rec.x_clients_birthday_str += f"{clients_date_value:%m/%d/%Y}"
            else:
                rec.x_clients_birthday_str = False

    # related field
    csm_ids = fields.One2many('cs.portal.csm', 'raw_ids', string='CSM')

    ### CSM MODEL START ###
class CSPortal_CSM(models.Model):
    _name = 'cs.portal.csm'
    _description = 'CS CSM'
    _rec_name = 'x_client_name_id'

    active = fields.Boolean(default=True)
    x_account = fields.Char('Account', store=True, index=True)
    x_client_name_id = fields.Char('Client Name', store=True)
    x_position = fields.Char('Position', store=True)
    
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Account Owner', index=True)
    secondary_owner_id = fields.Many2one('cs.portal.secondary.owner', string='Secondary Owner')
    x_decision_maker = fields.Selection([('decision maker', 'Decision Maker'), ('influencer', 'Influencer')],
                                        'Decision Maker/Influencer', store=True)
    x_status = fields.Selection([('positive', 'Positive'), ('neutral', 'Neutral'), ('detractor', 'Detractor')],
                                'Status', store=True)
    x_space_type = fields.Selection([('white', 'White'), ('blank', 'Blank')], 'White/Black Space', store=True)
    x_buyer = fields.Selection([('y', 'Y'), ('n', 'N')], 'Buyer', store=True)
    x_ap_responsibility = fields.Selection([('y', 'Y'), ('n', 'N')], 'AP Responsibility', store=True)
    x_comments = fields.Char('Comments', store=True)
    x_clients_birthday = fields.Date('Clients Birthday', store=True)
    # account_accountable_id = fields.Many2many('cs.portal.accountable', string='Accountable', index=True)
    x_account_type = fields.Text('Key/Non-key Account', store=True)
    x_revenue = fields.Char('Revenue', store=True)

    # related field
    raw_ids = fields.Many2many('cs.portal.raw', string='Raw')

### CSM MODEL END ###
    
#Accountable START
class CSPortal_Accountable(models.Model):
    _name = 'cs.portal.accountable'
    _description = 'Accountable'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Accountable', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Accountable Owner already exists!'),
    ]
### ACCOUNTABLE MODEL END ###

# Sales Pipeline Model Start#
class CSPortal_Pipeline(models.Model):
    _name = 'cs.portal.sales.pipeline'
    _description = 'Sales Pipeline'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Stage Name', store=True, index=True, required=True)

### Sales Pipeline Model End###
    
# General Pipeline Model Start#
class CSPortal_General_Pipeline(models.Model):
    _name = 'cs.portal.general.pipeline'
    _description = 'General Pipeline'
    _fold_name = 'fold'

    active = fields.Boolean(default=True)
    name = fields.Char('Stage Name', store=True, index=True, required=True)
    fold = fields.Boolean('Folded in Pipeline')
### General Pipeline Model End ###

### Account Planning Start ###
class CSPortal_Account_Planning(models.Model):
    _name = 'cs.portal.account.planning'
    _description = 'Account Planning'
    _rec_name = 'active'

    active = fields.Boolean(default=True)
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    date_created = fields.Datetime('Date Created', store=True)
    subject = fields.Char('Subject', store=True, required=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    goals_and_objectives = fields.Html('Goals', store=True)
    course_of_action = fields.Html('Actions', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Point Person')
    forecasting_headcount = fields.Integer('Forecasting Headcount', store=True)
    due_date = fields.Date('Due Date', store=True)
    update_log = fields.Text('History Logs', store=True)
    target_revenue = fields.Float('Target Revenue Last Year', store=True)
    ap_logs_ids = fields.One2many('cs.portal.logs', 'related_record_id', 'Logs')
    trv_to_achieve = fields.Float('Target Revenue to Achieve', store=True)

    @api.onchange('date_created')
    def _date_created_onchange_logs(self):
        for record in self:
            if record.date_created != record._origin.date_created:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_datetime': record._origin.date_created,
                    'nv_datetime': record.date_created,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Date Created'
                })
    
    # @api.onchange('account_owner_id')
    # def _account_owner_id_onchange_logs(self):
    #     for record in self:
    #         if record.account_owner_id != record._origin.account_owner_id:
    #             new_log = self.env['cs.portal.logs'].create({
    #                 'ov_char': record._origin.account_owner_id.name,
    #                 'nv_char': record.account_owner_id.name,
    #                 'related_record_id': record._origin.id,
    #                 'updated_field': 'Point Person'
    #             })

    @api.onchange('subject')
    def _subject_onchange_logs(self):
        for record in self:
            if record.subject != record._origin.subject:
                new_log = self.env['cs.portal.logs'].create({
                    'related_record_id': record._origin.id,
                    'updated_field': 'Subject',
                    'ov_char': record._origin.subject,
                    'nv_char': record.subject,
                })

    @api.onchange('forecasting_headcount')
    def _forecasting_headcount_onchange_logs(self):
        for record in self:
            if record._origin.forecasting_headcount != record.forecasting_headcount:
                new_log = self.env['cs.portal.logs'].create({
                    'related_record_id': record._origin.id,
                    'updated_field': 'Forecasting Headcount',
                    'ov_integer': record._origin.forecasting_headcount,
                    'nv_integer': record.forecasting_headcount,
                })     

    @api.onchange('target_revenue')
    def _target_revenue_onchange_logs(self):
        for record in self:
            if record.target_revenue != record._origin.target_revenue:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_float': record._origin.target_revenue,
                    'nv_float': record.target_revenue,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Target Revenue Last Year'
                })

    @api.onchange('due_date')
    def _due_date_onchange_logs(self):
        for record in self:
            if record.due_date != record._origin.due_date:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_date': record._origin.due_date,
                    'nv_date': record.due_date,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Due Date'
                })

    @api.onchange('goals_and_objectives')
    def _goals_and_objectives_onchange_logs(self):
        for record in self:
            if record.goals_and_objectives != record._origin.goals_and_objectives:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_html': record._origin.goals_and_objectives,
                    'nv_html': record.goals_and_objectives,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Goals'
                })

    @api.onchange('course_of_action')
    def _course_of_action_onchange_logs(self):
        for record in self:
            if record.course_of_action != record._origin.course_of_action:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_html': record._origin.course_of_action,
                    'nv_html': record.course_of_action,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Actions'
                })

    @api.onchange('status')
    def _status_onchange_logs(self):
        for record in self:
            if record.status != record._origin.status:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_char': record._origin.status,
                    'nv_char': record.status,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Status'
                })

    @api.onchange('trv_to_achieve')
    def _trv_to_achieve_onchange_logs(self):
        for record in self:
            if record.trv_to_achieve != record._origin.trv_to_achieve:
                new_log = self.env['cs.portal.logs'].create({
                    'ov_float': record._origin.trv_to_achieve,
                    'nv_float': record.trv_to_achieve,
                    'related_record_id': record._origin.id,
                    'updated_field': 'Target Revenue to Achieve'
                })

### Logs Start ###
class CSPortal_Logs(models.Model):
    _name = 'cs.portal.logs'
    _description = 'Logs'
    _order = "priority desc, id desc"
    _rec_name = 'id'
    
    active = fields.Boolean(default=True)
    field_type = fields.Selection([('char', 'Char'), ('integer', 'Integer'), 
                               ('boolean', 'Boolean'), ('float', 'Float'),
                               ('date', 'Date'), ('datetime', 'Datetime'),
                               ('text', 'Text')], "Field Type", store=True)
    related_record_id = fields.Many2one('cs.portal.account.planning', 'Related Record', store=True)
    priority = fields.Char('Priority', store=True)
    user_id = fields.Many2one('res.users', 'Responsible User', compute='_compute_user', store=True)
    updated_field = fields.Char('Updated Field', store=True)  

    # Old Value #
    ov_integer = fields.Integer('Old Value Integer', readonly=True)
    ov_float = fields.Float('Old Value Float', readonly=True)
    ov_char = fields.Char('Old Value Char', readonly=True)
    ov_text = fields.Text('Old Value Text', readonly=True)
    ov_date = fields.Date('Old Value Date', store=True)
    ov_datetime = fields.Datetime('Old Value DateTime', readonly=True)
    ov_html = fields.Html('Old Value Html', readonly=True)
    ov_final = fields.Html('Old Value', compute='_compute_final_value', store=True)

    # New Value #
    nv_integer = fields.Integer('New Value Integer', readonly=True)
    nv_float = fields.Float('New Value Float', readonly=True)
    nv_char = fields.Char('New Value Char', readonly=True)
    nv_text = fields.Text('New Value Text', readonly=True)
    nv_date = fields.Date('New Value Date', store=True)
    nv_datetime = fields.Datetime('New Value Datetime', readonly=True)
    nv_html = fields.Html('New Value Html', readonly=True)
    nv_final = fields.Html('New Value', compute='_compute_final_value', store=True)

    @api.depends('active')
    def _compute_user(self):
        for record in self:
            record.user_id = self.env.uid

    @api.depends('ov_final', 'nv_final')    
    def _compute_final_value(self):
        for record in self:
            if record.ov_integer != False or record.ov_integer != 0:
                record.ov_final = record.ov_integer                 
            if record.ov_float != False or record.ov_float != 0:
                record.ov_final = record.ov_float                      
            if record.ov_char != False or record.ov_char:
                record.ov_final = record.ov_char                      
            if record.ov_text != False:
                record.ov_final = record.ov_text                      
            if record.ov_date != False:
                record.ov_final = record.ov_date                      
            if record.ov_datetime != False:
                record.ov_final = record.ov_datetime
            if record.ov_html != False:
                record.ov_final = record.ov_html 
            if record.nv_integer != False or record.nv_integer != 0:
                record.nv_final = record.nv_integer                           
            if record.nv_float != False or record.nv_float != 0:
                record.nv_final = record.nv_float                           
            if record.nv_char != False:
                record.nv_final = record.nv_char                           
            if record.nv_text != False:
                record.nv_final = record.nv_text                           
            if record.nv_date != False:
                record.nv_final = record.nv_date                           
            if record.nv_datetime != False:
                record.nv_final = record.nv_datetime    
            if record.nv_html != False:
                record.nv_final = record.nv_html    
                
class CSPortal_Separation_Status(models.Model):
    _name = 'cs.portal.separation.status'
    _description = 'Separation Status'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Separation Status', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Separation Status already exists!'),
    ]

class CSPortal_Reason_For_Separation(models.Model):
    _name = 'cs.portal.reason.for.separation'
    _description = 'REASON For Separation (Resignation Letter/ Termination notice)'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Reason for Separation (Resignation Letter/ Termination notice) ', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Reason for Separation already exists!'),
    ]

class CSPortal_Reason_For_Separation(models.Model):
    _name = 'cs.portal.reason.for.separation'
    _description = 'REASON For Separation (Resignation Letter/ Termination notice)'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Reason for Separation (Resignation Letter/ Termination notice) ', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Reason for Separation already exists!'),
    ]

# Master File #
class CSPortal_Master_File(models.Model):
    _name = 'cs.portal.master.file'
    _description = 'Master File'
    _rec_name = 'account_name'

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    active = fields.Boolean(default=True)
    employee_id = fields.Char('Employee ID', store=True)
    account_name = fields.Char('Account Name', store=True, required=True)
    last_name = fields.Char('Last Name', store=True)
    first_name = fields.Char('First Name', store=True)
    start_date = fields.Date('Client Start Date', store=True)
    department = fields.Selection([('operations', 'OPERATIONS'),
                                       ('support', 'SUPPORT')], 'Department', store=True)
    company = fields.Selection([('isupport', 'iSupport'), ('iswerk', 'iSWerk')], 'Company', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='Owner', index=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    remarks = fields.Text('Remarks', store=True)
### Master File Model End###

class CSPortal_Position(models.Model):
    _name = 'cs.portal.position'
    _description = 'Position'
    _rec_name = 'name'

    active = fields.Boolean(default=True)
    name = fields.Char('Position', store=True, required=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Position already exists!'),
    ]

# Growth 2 START
# class CSPortal_Growth(models.Model):
#     _name = 'cs.portal.growth'
#     _description = 'Growth 2'
#     _rec_name = 'account_name'

#     cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
#     active = fields.Boolean(default=True)
#     created_on = fields.Datetime('Created on', store=True, required=True)
#     account_name = fields.Char('Client Name', store=True, compute='_compute_cs_portal_main_id')
#     headcount_demand = fields.Char('Headcount Demand', store=True)
#     job_title = fields.Char('Job Title', store=True)
#     req_id = fields.Char('Requisition ID', store=True)
#     req_status = fields.Selection([('for calibration', 'For Calibration'),
#                                ('open', 'Open'),
#                                ('reopened', 'Reopened'),
#                                ('ongoing sourcing', 'Ongoing Sourcing'),
#                                ('on hold', 'On Hold'),
#                                ('cancelled', 'Cancelled'),
#                                ('filled', 'Filled'),
#                                ('completed', 'Completed'),], 'Requisition Status', store=True, default='open')
#     req_position_classification = fields.Selection([('growth', 'Growth'), 
#                                ('new', 'New'),
#                                ('backfill', 'Backfill'),
#                                ('support_hiring', 'Support Hiring')], 'Position Classification', store=True)
#     backfill = fields.Integer('Backfill', store=True, compute='_compute_growth2_backfill')
#     growth = fields.Integer('Growth', store=True, compute='_compute_growth2_growth')
#     new_1 = fields.Integer('1New', store=True, compute='_compute_growth2_new1')
#     growth_1 = fields.Integer('1Growth', store=True, compute='_compute_growth2_growth_1')
#     month = fields.Char('Month', store=True, compute='_compute_month')
#     year = fields.Char('Year', store=True, compute='_compute_year')
#     filter = fields.Integer('Filter', store=True, compute='_compute_filter')
#     month_count = fields.Integer('Month Count', store=True, compute='_compute_month_count')
#     account_grew = fields.Char('Account Grew', store=True)
#     account_owner_id = fields.Many2one('cs.portal.account.owner', compute="_compute_account_owner_id", string='CSM2', index=True)
#     # account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM2', index=True)
#     status = fields.Selection([('new', 'New'),
#                                ('pending', 'Pending'),
#                                ('completed', 'Completed'), ], 'Status', store=True, default='new')
#     remarks = fields.Text('Remarks', store=True)
#     # Backfill computation per month
    
#     backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', compute='_compute_backfilled_hc_per_dec', store=True)
#     # backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', store=True)
#     backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', compute='_compute_backfilled_hc_per_jan', store=True)
#     # backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', store=True)
#     backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', compute='_compute_backfilled_hc_per_feb', store=True)
#     # backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', store=True)

# Growth 2 END

#Updated Raw Data Dashboard
class CSPortal_Growth(models.Model):
    _name = 'cs.portal.growth'
    _description = 'Growth 2'
    _rec_name = 'account_name'

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    active = fields.Boolean(default=True)
    created_on = fields.Datetime('Created on', store=True, required=True)
    ongoing_sourcing_date = fields.Datetime('Ongoing Sourcing Date', store=True)
    calibration_availability = fields.Datetime('Calibration Availability for Calibration Call', store=True)
    # account_name = fields.Char('Client Name', store=True, compute='_compute_cs_portal_main_id')
    account_name = fields.Char('Client Name', store=True)
    headcount_demand = fields.Integer('Headcount Demand', store=True)
    hiring_manager = fields.Char('Hiring Manager', store=True)
    hiring_manager_email_address = fields.Char('Hiring Manager Email Address', store=True)
    job_title = fields.Char('Job Title', store=True)
    requestor = fields.Char('Requestor', store=True, required=True)
    req_id = fields.Char('Requisition ID', store=True, required=True)
    req_status = fields.Selection([('for calibration', 'For Calibration'),
                                   ('for_pooling', 'For Pooling'),
                                ('open', 'Open'),
                                ('reopened', 'Reopened'),
                                ('ongoing sourcing', 'Ongoing Sourcing'),
                                ('on hold', 'On Hold'),
                                ('cancelled', 'Cancelled'),
                                ('recalibrate', 'Recalibrate'),
                                ('filled', 'Filled'),
                                ('completed', 'Completed'),], 'Requisition Status', store=True, default='open')
    salary_package = fields.Char('Salary Package', store=True)
    recruitment_manager = fields.Selection([('erma_san_miguel', 'Erma San Miguel'),
                                                ('rodney_ynares', 'Rodney Ynares'),
                                                ('alekcie_vergara', 'Alekcie Vergara'),
                                                ('cesar_jules_van_cayabat', 'Cesar Jules Van Cayabat'),
                                                ('erlyn_ferrer', 'Erlyn Ferrer'),
                                                ('ronald_dayon_dayon', 'Ronald Dayon Dayon'),
                                                ('donna_lyn_flores', 'Donna-lyn Flores')], 'Recruitment Manager', store=True)
    assigned_recruiter = fields.Char('Assigned Recruiter', store=True)
    industry = fields.Selection([('back_office', 'Back Office'),
                                ('customer_service', 'Customer Service'),
                                ('digital', 'Digital'),
                                ('finance', 'Finance'),
                                ('medical', 'Medical'),
                                ('operations_support', 'Operations Support'),
                                ('sales', 'Sales'),
                                ('supply_chain', 'Supply Chain'),
                                ('tech', 'Tech')], 'Industry', store=True)
    job_classification = fields.Selection([('generic', 'Generic'),
                                               ('tech', 'Tech'),
                                               ('niche', 'Niche'),
                                               ('executive', 'Executive')], 'Job Classification', store=True)
    req_position_classification = fields.Selection([('growth', 'Growth'), 
                                ('new', 'New'),
                                ('backfill', 'Backfill'),
                                ('support_hiring', 'Support Hiring')], 'Position Classification', store=True)
    # month = fields.Char('Month', store=True, compute='_compute_month')
    month = fields.Char('Month', store=True)
    # year = fields.Char('Year', store=True, compute='_compute_year')
    year = fields.Char('Year', store=True)
    # account_owner_id = fields.Many2one('cs.portal.account.owner', compute="_compute_account_owner_id", string='CSM', index=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', store=True)
    count_backfill = fields.Integer('Count Backfill', store=True)
    status = fields.Selection([('new', 'New'),
                                ('pending', 'Pending'),
                                ('completed', 'Completed')], 'Status', store=True, default='new')
    remarks = fields.Text('Remarks', store=True)

    #old raw data dashboard fields
    growth = fields.Integer('Growth', store=True, compute='_compute_growth2_growth')
    new_1 = fields.Integer('1New', store=True, compute='_compute_growth2_new1')
    growth_1 = fields.Integer('1Growth', store=True, compute='_compute_growth2_growth_1')
    backfill = fields.Integer('Backfill', store=True, compute='_compute_growth2_backfill')
    filter = fields.Integer('Filter', store=True, compute='_compute_filter')
    month_count = fields.Integer('Month Count', store=True, compute='_compute_month_count')
    account_grew = fields.Char('Account Grew', store=True)
        # Backfill computation per month
    backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', compute='_compute_backfilled_hc_per_dec', store=True)
        # backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', store=True)
    backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', compute='_compute_backfilled_hc_per_jan', store=True)
        # backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', store=True)
    backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', compute='_compute_backfilled_hc_per_feb', store=True)
        # backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', store=True)

# Growth 2 END
    
    @api.depends('backfill')
    def _compute_backfilled_hc_per_dec(self):
        for record in self:
            dec_growth = self.search([('month', '=', 'December')])
            record.backfilled_hc_per_dec = sum(dec_growth.backfill for dec_growth in dec_growth)

    @api.depends('backfill')
    def _compute_backfilled_hc_per_jan(self):
        for record in self:
            jan_growth = self.search([('month', '=', 'January')])
            record.backfilled_hc_per_jan = sum(jan_growth.backfill for jan_growth in jan_growth)

    @api.depends('backfill')
    def _compute_backfilled_hc_per_feb(self):
        for record in self:
            feb_growth = self.search([('month', '=', 'February')])
            record.backfilled_hc_per_feb = sum(feb_growth.backfill for feb_growth in feb_growth)

    @api.depends('req_status', 'req_position_classification', 'headcount_demand')
    def _compute_growth2_backfill(self):
        for rec in self:
            if rec.req_status != "on hold" and rec.req_status != "cancelled" and rec.req_position_classification == "backfill":
                rec.backfill = rec.headcount_demand
            else:
                rec.backfill = 0

    @api.depends('req_status', 'req_position_classification', 'headcount_demand')
    def _compute_growth2_growth(self):
        for record in self:
            if record.req_status not in ['on hold', 'cancelled']:
                if record.req_position_classification == 'growth':
                    record.growth = record.headcount_demand
                elif record.req_position_classification == 'new':
                    record.growth = record.headcount_demand
                else:
                    record.growth = 0
            else:
                record.growth = 0
    
    @api.depends('req_status', 'req_position_classification', 'headcount_demand')
    def _compute_growth2_new1(self):
        for rec in self:
            if rec.req_status != "on hold" and rec.req_status != "cancelled" and rec.req_position_classification == "new":
                rec.new_1 = rec.headcount_demand
            else:
                rec.new_1 = 0
    
    @api.depends('req_status', 'req_position_classification', 'headcount_demand')
    def _compute_growth2_growth_1(self):
        for record in self:
            if record.req_status not in ['on hold', 'cancelled']:
                if record.req_position_classification == 'growth':
                    record.growth_1 = record.headcount_demand
                elif record.req_position_classification == 'growth':
                    record.growth = record.headcount_demand
                else:
                    record.growth_1 = 0
            else:
                record.growth_1 = 0

    @api.depends('created_on')
    def _compute_month(self):
        for record in self:
            if record.created_on:
                record.month = record.created_on.strftime("%B")

    @api.depends('created_on')
    def _compute_year(self):
        for record in self:
            if record.created_on:
                record.year = str(record.created_on.year)

    @api.depends('backfill', 'new_1', 'growth')
    def _compute_filter(self):
        for record in self:
            if sum([record.backfill, record.new_1, record.growth]) == 0:
                record.filter = 0
            else:
                record.filter = 1

    @api.depends('month')
    def _compute_month_count(self):
        for record in self:
            # Convert month name to title case for consistency
            month_name = record.month.strip().title() if record.month else ''
            # Parse the month name into a datetime object and extract the month
            month_count = datetime.strptime(month_name, '%B').month if month_name else 0
            record.month_count = month_count

    @api.depends('account_name')
    def _compute_account_owner_id(self):
        for record in self:
            record.account_owner_id = record.cs_portal_main_id.account_owner_id

    @api.depends('cs_portal_main_id')
    def _compute_cs_portal_main_id(self):
        for record in self:
            record.account_name = record.cs_portal_main_id.account_name

# Recruitment To CS Target START
class CSPortal_Rect_To_CS_Target(models.Model):
    _name = 'cs.portal.rect.to.cs.target'
    _description = 'Rect To CS Target'
    _rec_name = 'month_count'

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    active = fields.Boolean(default=True)
    month_count = fields.Integer('Month Count', store=True)
    month = fields.Char('Month', store=True)
    year = fields.Char('Year', store=True)
    recruitment = fields.Char('Recruitment', store=True)
    cs_sales = fields.Char('CS + Sales', store=True)
    c2 = fields.Char('C2', store=True)
    met = fields.Char('Met', store=True)
    account_grown = fields.Char('Account Which Grown', store=True)
    hc_actual = fields.Char('HC Actual', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    remarks = fields.Text('Remarks', store=True)
# Recruitment To CS Target END

# Active Clients START
class CSPortal_Active_Clients(models.Model):
    _name = 'cs.portal.active.clients'
    _description = 'Active Clients'
    _rec_name = 'account_name'

    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    active = fields.Boolean(default=True)
    # account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', compute='_compute_account_owner_id', index=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', index=True)
    # account_status = fields.Selection([('active', 'Active'),
    #                                    ('inactive', 'Inactive'),
    #                                    ('sourcing', 'Sourcing')], 'Account Status', compute='_compute_cs_portal_main_id', store=True)
    account_status = fields.Selection([('active', 'Active'),
                                       ('inactive', 'Inactive'),
                                       ('sourcing', 'Sourcing')], 'Account Status', store=True)
    month = fields.Char('Month', required=True, store=True)
    # account_name = fields.Char('Account Name', store=True, compute='_compute_cs_portal_main_id')
    account_name = fields.Char('Account Name', store=True)
    # account = fields.Integer('Account', compute='_compute_account', store=True)
    account = fields.Integer('Account', store=True)
    # running_hc = fields.Integer('Running HC', compute='_compute_running_hc', store=True)
    running_hc = fields.Integer('Running HC', store=True)
    year = fields.Char('Year', store=True)
    # attrition_voluntary = fields.Integer('Attrition Voluntary', compute='_compute_attrition_voluntary', store=True)
    attrition_voluntary = fields.Integer('Attrition Voluntary', store=True)
    # attrition_involuntary = fields.Integer('Attrition Involuntary', compute='_compute_attrition_involuntary', store=True)
    attrition_involuntary = fields.Integer('Attrition Involuntary', store=True)
    # attrition_hc_per_account = fields.Integer('Attrition HC per Account', compute='_compute_attrition_hc_per_account', store=True)
    attrition_hc_per_account = fields.Integer('Attrition HC per Account', store=True)
    # backfill_share = fields.Float('Backfill Share%', compute='_compute_backfill_share', store=True, digits=(12, 0), readonly=True)

    backfill_share = fields.Float('Backfill Share%', store=True, digits=(12, 0))
    # backfilled_hc_per_account = fields.Integer('Backfilled HC per Account', compute='_compute_backfilled_hc_per_account', store=True)
    backfilled_hc_per_account = fields.Integer('Backfilled HC per Account', store=True)
    backfilled_hc = fields.Integer('Backfilled HC', store=True)
    # backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', compute='_compute_backfilled_hc_per_dec', store=True)
    backfilled_hc_per_dec = fields.Integer('Backfilled HC Per December', store=True)
    # backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', compute='_compute_backfilled_hc_per_jan',  store=True)
    backfilled_hc_per_jan = fields.Integer('Backfilled HC Per January', store=True)
    # backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', compute='_compute_backfilled_hc_per_feb', store=True)
    backfilled_hc_per_feb = fields.Integer('Backfilled HC Per February', store=True)
    backfilled_hc_per_mar = fields.Integer('Backfilled HC Per March', store=True)
    backfilled_hc_per_apr = fields.Integer('Backfilled HC Per April', store=True)
    backfilled_hc_per_may = fields.Integer('Backfilled HC Per May', store=True)
    backfilled_hc_per_jun = fields.Integer('Backfilled HC Per June', store=True)
    # growth_hc = fields.Integer('Growth HC', compute='_compute_growth_hc', store=True)
    growth_hc = fields.Integer('Growth HC', store=True)
    # growth_share = fields.Integer('Growth Share%', store=True)
    # growth_share = fields.Float('Growth Share', compute='_compute_growth_share', store=True)
    growth_share = fields.Float('Growth Share', store=True)
    # growth_client_hc = fields.Integer('Growth Client HC', compute='_compute_growth_client_hc', store=True)
    growth_client_hc = fields.Integer('Growth Client HC', store=True)
    # segment = fields.Selection([('small', 'Small'),
    #                                    ('medium', 'Medium'),
    #                                    ('large', 'Large')], 'Segment', compute='_compute_segment', store=True)
    segment = fields.Selection([('small', 'Small'),
                                       ('medium', 'Medium'),
                                       ('large', 'Large')], 'Segment', store=True)
    # growth_client_jan = fields.Integer('Growth Client January', compute='_compute_growth_client_jan', store=True)
    growth_client_jan = fields.Integer('Growth Client January', store=True)
    # growth_client_feb = fields.Integer('Growth Client February', compute='_compute_growth_client_feb', store=True)
    growth_client_feb = fields.Integer('Growth Client February', store=True)
    # growth_client_dec = fields.Integer('Growth Client December', compute='_compute_growth_client_dec', store=True)
    growth_client_dec = fields.Integer('Growth Client December', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    remarks = fields.Text('Remarks', store=True)
    # date_today = fields.Datetime('Date Today Trigger', compute="_compute_date_today")
    date_today = fields.Datetime('Date Today Trigger')

    # Date Today Function
    @api.depends('date_today')
    def _compute_date_today(self):
        for record in self:
            record.date_today = datetime.today()


# Active Clients END
    # Compute method to calculate backfilled_hc_per_account
    # @api.depends('backfilled_hc_per_dec', 'backfilled_hc_per_jan', 'backfilled_hc_per_feb')
    @api.depends('backfilled_hc_per_dec', 'backfilled_hc_per_jan', 'backfilled_hc_per_feb')
    def _compute_backfilled_hc_per_account(self):
        for record in self:
            record.backfilled_hc_per_account = record.backfilled_hc_per_dec + record.backfilled_hc_per_jan + record.backfilled_hc_per_feb
    
    # @api.depends('backfilled_hc_per_account')
    # def _compute_backfill_share(self):
    #     total_backfilled_hc = sum(record.backfilled_hc_per_account for record in self.search([]))
    #     for record in self:
    #         record.backfilled_hc_per_account = record.backfilled_hc_per_account / total_backfilled_hc if total_backfilled_hc else 0.0

    # Compute method to calculate backfill_share
    @api.depends('backfilled_hc_per_account')
    def _compute_backfill_share(self):
        total_backfilled_hc = sum(self.mapped('backfilled_hc_per_account'))
        for record in self:
            backfilled_hc_per_account_value = record.backfilled_hc_per_account
            record.backfill_share = int((backfilled_hc_per_account_value / total_backfilled_hc) * 100) if total_backfilled_hc != 0 else 0.0
    
    @api.depends('date_today')
    def _compute_date_today(self):
        self.date_today = datetime.today()

    @api.depends('account_name')
    def _compute_account_owner_id(self):
        for record in self:
            record.account_owner_id = record.cs_portal_main_id.account_owner_id

    @api.depends('cs_portal_main_id')
    def _compute_cs_portal_main_id(self):
        for record in self:
            record.account_status = record.cs_portal_main_id.account_status
            record.account_name = record.cs_portal_main_id.account_name
    
    # @api.depends('cs_portal_main_id')
    # def _compute_account_name(self):
    #     for record in self:
    #         record.account_name = record.cs_portal_main_id.account_name

    # @api.depends('cs_portal_main_id.account_name')
    # def _compute_account(self):
    #     for record in self:
    #         # Count all records with the same account_name
    #         account_count = self.env['cs.portal.active.clients'].search_count([
    #             ('account_name', '=', record.account_name)
    #             ])
    #         record.account = account_count
    
    @api.depends('cs_portal_main_id.isw_headcount')
    def _compute_running_hc(self):
        for record in self:
            record.running_hc = record.cs_portal_main_id.isw_headcount
    
    @api.depends('month', 'account_name')
    def _compute_attrition_voluntary(self):
        for record in self:
            voluntary_count = self.env['cs.portal.attrition.and.backfills'].search_count([
                ('month', '=', record.month),
                ('account_name', '=', record.account_name),
                ('voluntary_involuntary', '=', 'voluntary')
            ])
            record.attrition_voluntary = voluntary_count

    @api.depends('month', 'account_name')
    def _compute_attrition_involuntary(self):
        for record in self:
            involuntary_count = self.env['cs.portal.attrition.and.backfills'].search_count([
                ('month', '=', record.month),
                ('account_name', '=', record.account_name),
                ('voluntary_involuntary', '=', 'involuntary')
            ])
            record.attrition_involuntary = involuntary_count

    @api.depends('attrition_voluntary', 'attrition_involuntary')
    def _compute_attrition_hc_per_account(self):
        for record in self:
            record.attrition_hc_per_account = record.attrition_voluntary + record.attrition_involuntary

    @api.depends('month', 'account_name')
    def _compute_backfilled_hc_per_dec(self):
        for record in self:
            dec_growth = self.env['cs.portal.growth'].search([('month', '=', 'December'),('account_name', '=', record.account_name)])
            record.backfilled_hc_per_dec = sum(dec_growth.backfill for dec_growth in dec_growth)

    @api.depends('month', 'account_name')
    def _compute_backfilled_hc_per_jan(self):
        for record in self:
            jan_growth = self.env['cs.portal.growth'].search([('month', '=', 'January'),('account_name', '=', record.account_name)])
            record.backfilled_hc_per_jan = sum(jan_growth.backfill for jan_growth in jan_growth)

    @api.depends('month', 'account_name')
    def _compute_backfilled_hc_per_feb(self):
        for record in self:
            feb_growth = self.env['cs.portal.growth'].search([('month', '=', 'February'),('account_name', '=', record.account_name)])
            record.backfilled_hc_per_feb = sum(feb_growth.backfill for feb_growth in feb_growth)
    
    @api.depends('account_name')
    def _compute_growth_hc(self):
        for record in self:
            hc_growth_records = self.env['cs.portal.growth'].search([('account_name', '=', record.account_name)])
            record.growth_hc = sum(hc_growth.growth for hc_growth in hc_growth_records)

    # api.depends('account_name')
    # def _compute_growth_hc(self):
    #     for record in self:
    #         hc_growth = self.env['cs.portal.growth'].search_count([
    #             ('account_name', '=', record.account_name),
    #             ('growth', '=', 'growth')
    #         ])
    #         record.growth_hc = sum(hc_growth.growth for hc_growth in hc_growth)

    @api.depends('account_name', 'month')
    def _compute_growth_client_hc(self):
        for record in self:
            # Search for matching records in cs.portal.growth
            hc_growth_client_records = self.env['cs.portal.growth'].search([
                ('account_name', '=', record.account_name),
                ('month', '=', record.month),
                ('growth', '>', 0)
            ])
            # Check if any record exists with a positive growth value
            if hc_growth_client_records:
                record.growth_client_hc = '1'
            else:
                record.growth_client_hc = '0'

    @api.depends('running_hc')
    def _compute_segment(self):
        for record in self:
            if record.running_hc <= 5:
                record.segment = 'small'
            elif record.running_hc <= 15:
                record.segment = 'medium'
            else:
                record.segment = 'large'

    @api.depends('account_name', 'month')
    def _compute_growth_client_jan(self):
        for record in self:
            growth_client_jan_records = self.env['cs.portal.growth'].search([
                ('account_name', '=', record.account_name),
                ('month', '=', 'January'),
                ('growth', '>', 0)
            ])
            record.growth_client_jan = 1 if growth_client_jan_records else 0

    @api.depends('account_name', 'month')
    def _compute_growth_client_feb(self):
        for record in self:
            growth_client_feb_records = self.env['cs.portal.growth'].search([
                ('account_name', '=', record.account_name),
                ('month', '=', 'February'),
                ('growth', '>', 0)
            ])
            record.growth_client_feb = 1 if growth_client_feb_records else 0

    @api.depends('account_name', 'month')
    def _compute_growth_client_dec(self):
        for record in self:
            growth_client_dec_records = self.env['cs.portal.growth'].search([
                ('account_name', '=', record.account_name),
                ('month', '=', 'December'),
                ('growth', '>', 0)
            ])
            record.growth_client_dec = 1 if growth_client_dec_records else 0

    @api.depends('growth_hc')
    def _compute_growth_share(self):
        total_growth_hc = sum(record.growth_hc for record in self.search([]))
        for record in self:
            record.growth_share = record.growth_hc / total_growth_hc if total_growth_hc else 0.0

    # @api.depends('growth_hc')
    # def _compute_growth_share(self):
    #     total_growth_hc = sum(record.growth_hc for record in self.search([]))
    #     for record in self:
    #         growth_share_value = record.growth_hc
    #         record.growth_share = int((growth_share_value / total_growth_hc) * 100) if total_growth_hc != 0 else 0

# Overall START
class CSPortal_Overall(models.Model):
    _name = 'cs.portal.overall'
    _description = 'Overall'
    _rec_name = 'month'
    
    cs_portal_main_id = fields.Many2one('cs.portal.main', string='CS Portal Main')
    active = fields.Boolean(default=True)
    month = fields.Char('Month', store=True)
    account_owner_id = fields.Many2one('cs.portal.account.owner', string='CSM', index=True)
    mbr_conducted = fields.Integer('MBR Conducted', store=True)
    mbr_scheduled = fields.Integer('MBR Scheduled', store=True)
    mbr_target = fields.Integer('MBR Target', store=True)
    mbr_actual = fields.Float('MBR Actual', store=True)
    backfill_attrition = fields.Integer('Backfill Attrition', store=True)
    # backfill_attrition = fields.Integer('Backfill Attrition', compute='_compute_backfill_attrition', store=True)
    backfill_backfilled = fields.Integer('Backfill Backfilled', store=True)
    backfill_actual = fields.Float('Backfill Actual', store=True)
    req_overall = fields.Integer('Requisition Overall', store=True)
    req_target = fields.Float('Requisition Target', store=True)
    req_backfill = fields.Integer('Requisition Backfill', store=True)
    req_cancelled = fields.Integer('Requisition Canncelled', store=True)
    req_growth = fields.Integer('Requisition Growth', store=True)
    req_new = fields.Integer('Requisition New', store=True)
    dormant_accounts = fields.Integer('Dormant Accounts', store=True)
    clients_grown = fields.Integer('Clients Grown', store=True)
    clients_grown_percentage = fields.Float('Clients Grown%', store=True)
    csat_score = fields.Integer('CSAT Score', store=True)
    csat_res_count = fields.Integer('CSAT Res Count', store=True)
    num_of_audit = fields.Integer('# of Audit', store=True)
    num_of_recordings = fields.Integer('# of Recordings', store=True)
    quality_assurance = fields.Float('QA%', store=True)
    nps_score = fields.Float('NPS Score', store=True)
    nps_promoter = fields.Integer('NPS Promoter', store=True)
    nps_passive = fields.Integer('NPS Passive', store=True)
    nps_detractor = fields.Integer('NPS Detractor', store=True)
    small = fields.Integer('Small', store=True)
    medium = fields.Integer('Medium', store=True)
    large = fields.Integer('Large', store=True)
    small_percentage = fields.Float('Small%', store=True)
    medium_percentage = fields.Float('Medium%', store=True)
    large_percentage = fields.Float('Large%', store=True)
    client_assignment = fields.Integer('Client Assignment', store=True)
    hc_population = fields.Integer('HC Population', store=True)
    status = fields.Selection([('new', 'New'),
                               ('pending', 'Pending'),
                               ('completed', 'Completed'), ], 'Status', store=True, default='new')
    remarks = fields.Text('Remarks', store=True)
# Overall END
