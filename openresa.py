# -*- coding: utf-8 -*-

##############################################################################
#
#    OpenResa module for OpenERP, module OpenResa
#    Copyright (C) 200X Company (<http://website>) pyf
#
#    This file is a part of OpenResa
#
#    OpenResa is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    OpenResa is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from datetime import datetime,timedelta
from osv import fields, osv
import netsvc
from tools.translate import _
from mx.DateTime.mxDateTime import strptime
import time
import types
import base64
import unicodedata
import re
import pytz
import calendar
import logging
import openerp
import os
import tools
from datetime import datetime
from siclic_time_extensions import weeks_between, days_between
import html_builder

# i create model in this file to avoid inter-dependance between hotel.reservation and this one
# actually, they have many2one on each other
#this object is fully implemented in openresa_recurrence.py file
class openresa_reservation_recurrence(osv.osv):
    _name = 'openresa.reservation.recurrence'
    _inherits = {'hotel.reservation':'template_id'}
    _columns = {
            'template_id':fields.many2one('hotel.reservation','Template', required=True, ondelete='cascade')
        }

openresa_reservation_recurrence()

class hotel_reservation_line(osv.osv):
    _name = "hotel_reservation.line"
    _inherit = "hotel_reservation.line"

    _AVAILABLE_ACTION_VALUES = [('nothing','Pas d\'intervention'),('inter','Intervention à générer'),('inter_ok','Intervention générée')]

    def name_get(self, cr, uid, ids, context=None):
        ret = []
        for line in self.browse(cr, uid, ids, context):
            ret.append((line.id,'%s %s' % (line.qte_reserves, line.reserve_product)))
        return ret

    def _get_state_line(self, cr, uid, context=None):
        res = self.pool.get("hotel.reservation").fields_get(cr, uid, 'state', context=context)
        return res['state']['selection']

    def _calc_qte_dispo(self, cr, uid, ids, name, args, context=None):
        prod_id_to_line = {}
        if not context:
            context = {}
        resa_ids = []
        ret = {}.fromkeys(ids,{'dispo':False,'qte_dispo':0.0})
        if 'qte_dispo' in name:
            #get all resa linked with lines
            for line in self.browse(cr, uid, ids):
                if line.line_id and not line.line_id.id in resa_ids:
                    resa_ids.append(line.line_id.id)
            #for each resa, compute the qty_available
            resa_obj = self.pool.get("hotel.reservation")
            for resa in resa_obj.browse(cr, uid, resa_ids):
                prod_ids = [x.reserve_product.id for x in resa.reservation_line]
                #get available prods_qty : {prod_id:qty}
                available = resa_obj.get_prods_available_and_qty( cr, uid, resa.checkin, resa.checkout, prod_ids=prod_ids, where_optionnel='and hr.id <> ' + str(resa.id), context=context)
                #link prod qty available to resa_line associated
                for line in resa.reservation_line:
                    ret.update({line.id:{'qte_dispo':available[str(line.reserve_product.id)]}})
                    if 'dispo' in name:
                        ret[line.id].update({'dispo':available[str(line.reserve_product.id)] >= line.qte_reserves})
        elif 'dispo' in name:
            for line in self.browse(cr, uid, ids):
                ret.update({line.id:{'dispo':line.qte_dispo >= line.qte_reserves}})
        return ret



    def _get_complete_name(self, cr, uid, ids, name, args, context=None):
        ret = {}
        weekday_to_str = {0:'Lundi',1:'Mardi',2:'Mercredi',3:'Jeudi',4:'Vendredi',5:'Samedi',6:'Dimanche'}
        for line in self.browse(cr, uid, ids, context=context):
            dt_checkin = fields.datetime.context_timestamp(cr, uid, datetime.strptime(line.checkin,'%Y-%m-%d %H:%M:%S'), context=context)
            dt_checkout = fields.datetime.context_timestamp(cr, uid, datetime.strptime(line.checkout,'%Y-%m-%d %H:%M:%S'), context=context)
            checkin = dt_checkin.strftime('%Y-%m-%d %H:%M:%S')
            checkout = dt_checkout.strftime('%Y-%m-%d %H:%M:%S')
            weekday_start = calendar.weekday(int(checkin[:4]), int(checkin[5:7]), int(checkin[8:10]))
            weekday_end = calendar.weekday(int(checkout[:4]), int(checkout[5:7]), int(checkout[8:10]))
            date_str = ''

            if weekday_start <> weekday_end:
                date_str = '%s %s - %s %s : ' % (weekday_to_str[weekday_start][:3],checkin[11:16],weekday_to_str[weekday_end][:3],checkout[11:16])
            ret[line.id] = '%s %d x %s (%s)' %(date_str,line.qte_reserves, line.reserve_product.name_template, line.partner_id.name)
        return ret

    """
    @param prod_dict: list of dict of prod and qty to retrieve values (represents produdcts needed for reservation) : [{'prod_id':id,'qty':qty_needed}]
    @param checkin-checkout: dates of checkin-checkout to test
    @return: lines for which current checkin-checkout and prod_dict are in conflicts
    @note: to be used in fields.function calculation and for other uses, as openresa.reservation.choices 'dispo' calculation
    """
    def get_global_conflicting_lines(self,cr, uid, prod_dict, checkin, checkout, context=None):
        ret = []
        prod_ids = [item['prod_id'] for item in prod_dict]
        #compute qties of products already in 'remplir' resa
        available = self.pool.get("hotel.reservation").get_prods_available_and_qty(cr, uid, checkin, checkout, prod_ids=prod_ids, states=['cancel','done','confirm','wait_confirm'], context=context)
        #for each prod desired, retrieve those which are conflicting
        conflicting_prods = []
        for item in prod_dict:
            if available[str(item['prod_id'])] < item['qty']:
                conflicting_prods.append(item['prod_id'])
        #and retrieve lines belonging to conflicting_prods and checkin-checkout
        if conflicting_prods:
            ret.extend(self.search(cr, uid, [('reserve_product.id','in',conflicting_prods),'|',
                                             '&',('line_id.checkin','>=',checkin),('line_id.checkin','<=',checkout),
                                             '&',('line_id.checkout','>=',checkin),('line_id.checkout','<=',checkout)],
                                   context=context))
        return ret


    def _get_conflicting_lines(self, cr, uid, ids, name, args, context=None):
        #by default, returns empty list
        ret = {}.fromkeys(ids,[])
        #get only lines in 'remplir' state
        for line in self.browse(cr, uid, ids, context=context):
            if line.line_id and line.line_id.state == 'remplir':
                ret[line.id] = self.get_global_conflicting_lines(cr, uid, [{'prod_id':line.reserve_product.id,'qty':line.qte_reserves}], line.line_id.checkin, line.line_id.checkout, context)
        return ret

    _columns = {
        'categ_id': fields.many2one('product.category','Type d\'article'),
        "reserve_product": fields.many2one("product.product", "Article réservé", domain=[('openstc_reservable','=',True)]),
        "qte_reserves":fields.float("Qté désirée", digits=(3,2)),
        'dispo':fields.function(_calc_qte_dispo, string="Disponible", method=True, multi="dispo", type='boolean'),
        "infos":fields.char("Informations supplémentaires",size=256),
        "name":fields.char('Libellé', size=128),
        'state':fields.related('line_id','state', type='selection',string='Etat Résa', selection=_get_state_line, readonly=True),
        'qte_dispo':fields.function(_calc_qte_dispo, method=True, string='Qté Dispo', multi="dispo", type='float'),
        'action':fields.selection(_AVAILABLE_ACTION_VALUES, 'Action'),
        'state':fields.related('line_id','state', type='char'),
        'partner_id':fields.related('line_id','partner_id', type="many2one", relation="res.partner"),
        'checkin':fields.related('line_id','checkin', type="datetime"),
        'checkout':fields.related('line_id','checkout', type="datetime"),
        'resa_name':fields.related('line_id','name',type="char"),
        'complete_name':fields.function(_get_complete_name, type="char", string='Complete Name', size=128)
        }

    _defaults = {
     'qte_reserves':lambda *a: 1,
     'state':'remplir',
     'action':'nothing',
        }

    #TODO: check if useless ?
    def plan_inter(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'action':'inter'})
        return {'type':'ir.actions.act_window.close'}
    #@TOCHECK: useless ?
    def unplan_inter(self, cr, uid, ids, context=None):
        self.write(cr, uid, ids, {'action':'nothing'})
        return {'type':'ir.actions.act_window.close'}

    '''' Get conflicting lines by product '''
    def get_lines_by_prod(self, cr, prod, checkin, checkout, states=['remplir'], where_optionnel=""):
        cr.execute("select hrl.id, hrl.qte_reserves \
                    from hotel_reservation_line as hrl \
                    join hotel_reservation as hr  on hr.id = hrl.line_id \
                    where reserve_product = %s \
                    and hr.state  in%s \
                    and (hr.checkin, hr.checkout) overlaps ( timestamp %s, timestamp %s ) \
                    " + where_optionnel , (prod, tuple(states), checkin, checkout))
        return cr

    #TODO : check lines (for non manager user only) : if product has max_qty, lines must not reserve more than max_qty of this product
    def _check_max_qties(self, cr, uid, ids, context=None):
        is_manager = self.pool.get("res.users").search(cr, uid, [('id','=',uid),('groups_id.code','=','HOTEL_MANA')])
        if not is_manager:
            for line in self.browse(cr, uid, ids, context=context):
                #if one line does not match criteria, return False and raise exception
                if line.reserve_product.max_bookable_qty and line.qte_reserves > line.reserve_product.max_bookable_qty:
                    return False
        return True

    _constraints = [(_check_max_qties, _('You can not reserve more than qty max for your product'), ['reserve_product','qte_reserves'])]

hotel_reservation_line()

class hotel_reservation(osv.osv):
    _name = "hotel.reservation"
    _order = "state_num, create_date desc"
    _inherit = "hotel.reservation"
    _description = "Réservations"

    def remove_accents(self, str):
        return ''.join(x for x in unicodedata.normalize('NFKD',str) if unicodedata.category(x)[0] == 'L')

    def _custom_sequence(self, cr, uid, context):
        seq = self.pool.get("ir.sequence").next_by_code(cr, uid, 'resa.number',context)
        return seq

    def get_resa_modified(self, cr, uid, ids, context=None):
        return ids

    def return_state_values(self, cr, uid, context=None):
        return [('draft', 'Saisie des infos personnelles'),('confirm','Réservation confirmée'),('cancel','Annulée'),('in_use','Réservation planifiée'),('done','Réservation Terminée'), ('remplir','Saisie de la réservation'),('wait_confirm','En Attente de Confirmation')]

    def _get_state_values(self, cr, uid, context=None):
        return self.return_state_values(cr, uid, context)

    def _get_state_num(self, cr, uid, ids,  name, args, context=None):
        res={}
        for obj in self.browse(cr, uid, ids, context):
            res[obj.id] = (obj.state=='remplir' and 1) or (obj.state=='draft' and 2) or (obj.state=='confirm' and 3) or (obj.state=='done' and 4) or 5
        return res

    """
    action rights for manager only
    - only manager can do it, because imply stock evolutions and perharps treatment of some conflicts
    """
    def managerOnly(self, cr, uid, record, groups_code):
        return 'HOTEL_MANA' in groups_code

    """
    action rights for manager or owner of a record
    - claimer can do these actions on its own records,
    - officer can make these actions for claimer which does not have account,
    - else, manager can also do it
    """
    def ownerOrOfficer(self, cr, uid, record, groups_code):
        #if not rights, compute rights for offi/manager
        ret = 'HOTEL_OFFI' in groups_code or 'HOTEL_MANA' in groups_code
        if not ret:
            #compute rights for owner
            for contact in record.partner_id.address:
                if uid == contact.user_id.id:
                    ret = True
                    break
            ret = ret and 'HOTEL_USER' in groups_code
        return ret

    _actions = {
        'confirm': lambda self,cr,uid,record, groups_code: self.managerOnly(cr, uid, record, groups_code)  and record.state == 'remplir',
        'cancel': lambda self,cr,uid,record, groups_code: self.managerOnly(cr, uid, record, groups_code)  and record.state == 'remplir',
        'done': lambda self,cr,uid,record, groups_code: self.managerOnly(cr, uid, record, groups_code) and record.state == 'confirm',
    }

    def _get_fields_resources(self, cr, uid, ids, name, args, context=None):
        res = {}

        for obj in self.browse(cr, uid, ids, context=context):
            res[obj.id] = {}
            field_ids = obj.reservation_line
            val = []
            for item in field_ids:
                if obj.state in ('remplir','cancel'):
                    tooltip = " souhaitée: " + str(int(item.qte_reserves))
                    if item.dispo and obj.state!='cancel' :
                        tooltip += " ,disponible: " + str(int(item.qte_dispo))
                else :
                    tooltip = " réservée : " + str(int(item.qte_reserves))
                val.append({'id': item.reserve_product.id,  'name' : item.reserve_product.name_get()[0][1], 'type': item.reserve_product.type_prod,  'quantity' : item.qte_reserves, 'tooltip' : tooltip})
            res[obj.id].update({'resources':val})
        return res

    def _get_actions(self, cr, uid, ids, myFields ,arg, context=None):
        #default value: empty string for each id
        ret = {}.fromkeys(ids,'')
        groups_code = []
        groups_code = [group.code for group in self.pool.get("res.users").browse(cr, uid, uid, context=context).groups_id if group.code]
        #evaluation of each _actions item, if test returns True, adds key to actions possible for this record
        for record in self.browse(cr, uid, ids, context=context):
            #ret.update({inter['id']:','.join([key for key,func in self._actions.items() if func(self,cr,uid,inter)])})
            ret.update({record.id:[key for key,func in self._actions.items() if func(self,cr,uid,record,groups_code)]})
        return ret

    def generate_html_plannings_for(self, cr, uid, bookable_ids, start_date, end_date):
        for planning in self.generate_plannings_for(cr, uid, bookable_ids, start_date, end_date):
            html_planning = self.format_plannings_with(planning, 'html')
        return html_planning

    def generate_plannings_for(self, cr, uid, bookable_ids, start_date, end_date):
        """
        This function generate weekly html plannings of the given resources.

        :param bookable_ids: The bookable resources ids included in plannings
        :param start_date: The start date of the planning
        :param end_date: Then end date of the planning
        :return: List[Dict['bookable_name':String, weeks: List[hotel_reservation]]]
        """
        weeks = weeks_between(datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S"),
                              datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S"))
        plannings = list()
        bookables = self.pool.get('product.product').read(cr, uid, bookable_ids, ['name'])
        for bookable in bookables:
            plannings.append(
                {'bookable_name': bookable['name'], 'weeks': self.event_list_for_weeks(cr, uid, bookable['id'], weeks)})
        return plannings

    def event_list_for_weeks(self, cr, uid, bookable_id, weeks):
        """
        Retrieve events for a given bookable, and given weeks

        :param bookable_id: Integer the bookable id
        :param weeks: a list of tuple [(datetime,datetime)]
        :return: List[List[hotel_reservation]]
        """
        bookable_events = list()
        for week in weeks:
            bookable_events.append(self.event_list_for_week(cr, uid, bookable_id, week))
        return bookable_events

    def event_list_for_week(self, cr, uid, bookable_id, week):
        """
        Retrieve events ids for a given bookable, and given week

        :param bookable_id: Integer the bookable id
        :param week: Tuple[Datetime, Datetime]
        :return: Dict['first_day':String,'last_day': String, 'bookings': Dict[datetime: List[hotel_reservation]]]
        """
        first_day = datetime.strftime(week[0], '%Y-%m-%d %H:%M:%S')
        last_day = datetime.strftime(week[1], '%Y-%m-%d %H:%M:%S')

        week_events_ids = self.search(cr, uid,
                                      [('reservation_line.reserve_product.id', '=', bookable_id),
                                       ('state', '=', 'confirm'),
                                       '|',
                                       '&', ('checkin', '>=', first_day), ('checkin', '<=', last_day),
                                       '&', ('checkout', '>=', first_day), ('checkout', '<=', last_day)])
        week_events = {'first_day': first_day, 'last_day': last_day,
                       'bookings': self.build_events_data_dictionary(cr, uid, week_events_ids)}

        week_days = days_between(week[0], week[1])
        events_by_day = list()
        for day in week_days:
            events_by_day.append((day, filter(lambda event: (event.get('start_hour').date() <= day.date()) &
                                                            (event.get('end_hour').date() >= day.date()),
                                              week_events.get('bookings'))))
        week_events['bookings'] = events_by_day
        return week_events

    def build_events_data_dictionary(self, cr, uid, event_ids):
        """
        Format data to expose weekly planning through API

        :param event_ids: List[Integer]
        :return: List[Dict]
        """
        events = self.read(cr, uid, event_ids,
                           ['name', 'checkin', 'checkout', 'partner_id', 'partner_order_id', 'resources',
                            'confirm_note'])

        events_dictionaries = map(lambda event:
                                  {
                                      'name': event.get('name'),
                                      'start_hour': datetime.strptime(event.get('checkin'), "%Y-%m-%d %H:%M:%S"),
                                      'end_hour':  datetime.strptime(event.get('checkout'), "%Y-%m-%d %H:%M:%S"),
                                      'booker_name': event.get('partner_id')[1],
                                      'contact_name': event.get('partner_order_id')[1],
                                      'resources': map(lambda r: {'name': r.get('name'), 'quantity': r.get('quantity')},
                                                       event.get('resources')),
                                      'note': event.get('confirm_note')
                                  },
                                  events)
        return events_dictionaries

    def format_plannings_with(self, plannings, req_format):
        if req_format == 'html':
            return html_builder.format_resource_plannings(plannings)


    _columns = {
        'create_uid': fields.many2one('res.users', 'Created by', readonly=True),
        'write_uid': fields.many2one('res.users', 'Writed by', readonly=True),
        'deleted_at': fields.date('Deleted date'),
        'confirm_at': fields.date('Confirm date'),
        'done_at': fields.date('Done date'),
        'cancel_at': fields.date('Cancel date'),
        'state': fields.selection(_get_state_values, 'Etat', readonly=True),
        'state_num': fields.function(_get_state_num, string='Current state', type='integer', method=True,
                                     store={'hotel.reservation': (get_resa_modified, ['state'], 20)}),
        'create_date': fields.datetime('Create Date', readonly=True),
        'write_date': fields.datetime('Write Date', readonly=True),

        'name': fields.char('Nom Manifestation', size=128, required=True),
        'resources': fields.function(_get_fields_resources, multi='field_resources', method=True,
                                        type='char', store=False),

        'site_id': fields.many2one('openstc.site', 'Site (Lieu)'),
        'prod_id': fields.many2one('product.product', 'Ressource'),
        'openstc_partner_id': fields.many2one('res.partner', 'Demandeur', help="Personne demandant la réservation."),
        'resa_checkout_id': fields.many2one('openstc.pret.checkout', 'Etat des Lieux associé'),
        
        'date_choices': fields.one2many('openresa.reservation.choice', 'reservation_id', 'Choices of dates'),
        'recurrence_id': fields.many2one('openresa.reservation.recurrence', 'From recurrence'),
        'is_template': fields.boolean('Is Template', help='means that this reservation is a template for a recurrence'),
        'actions': fields.function(_get_actions, method=True, string="Actions possibles", type="char", store=False),
        
        'partner_type': fields.related('partner_id', 'type_id', type='many2one', relation='openstc.partner.type',
                                       string='Type du demandeur', help='...'),
        'contact_phone': fields.related('partner_invoice_id', 'phone', type='char', string='Phone contact', help='...'),
        'partner_mail': fields.char('Email Demandeur', size=128, required=False),
        'people_name': fields.char('Name', size=128),
        'people_phone': fields.char('Phone', size=10),
        'people_street':fields.char('Street',size=128),
        'people_city':fields.char('City',size=64),
        'people_zip':fields.char('Zip',size=5),
        'is_citizen': fields.boolean('Claimer is a citizen'),

        'note': fields.text('Note de validation'),
        'whole_day':fields.boolean('Whole day'),
    }
    _defaults = {
                 'state': lambda *a: 'remplir',
                 'reservation_no': lambda self,cr,uid,ctx=None:self._custom_sequence(cr, uid, ctx),
        }

    def search(self, cr, uid, args, offset=0, limit=None, order=None, context=None, count=False):
        if order in (' ',''): order=None
        #Keep simple resa and only template for reccurence
        deleted_domain = []
        for s in args :
            if 'deleted_at' in s:
                args.remove(s)
                deleted_domain = [('deleted_at','=', False)]
        args.extend(deleted_domain)
        return super(hotel_reservation, self).search(cr, uid, args, offset, limit, order, context, count)

    def _check_dates(self, cr, uid, ids, context=None):
        for resa in self.browse(cr, uid, ids, context):
            if resa.checkin >= resa.checkout:
                return False
        return True

    _constraints = [(_check_dates, _("Your checkin is greater than your checkout, please modify them"), ['checkin','checkout'])]

    def format_vals(self, cr, uid, values, context=None):
        def force_seconds_date(vals):
            if vals and len(vals) > 16:
                vals = vals[:16] + ':00'
            return vals
        if 'checkin' in values:
            values['checkin'] = force_seconds_date(values.get('checkin'))
        if 'checkout' in values:
            values['checkout'] = force_seconds_date(values.get('checkout'))
        return values

    def resolve_default_booking_contact(self, cr, uid, partner_id):
        """
        Return default booking contact for given partner
        :param partner_id: int
        :return:
        """
        partner_ids = self.pool.get('res.partner.address').search(cr, uid, [('partner_id.id', '=', partner_id)])
        if not partner_ids:
            raise osv.except_osv('Inconsistent Data', 'The partner is missing a contact')
        else:
            return partner_ids[0]

    def create(self, cr, uid, values, context=None):
        if not 'state' in values or values['state'] == 'remplir':
            values['shop_id'] = self.pool.get("sale.shop").search(cr, uid, [], limit=1)[0]
        self.format_vals(cr, uid, values, context=context)
        if not (type(values['partner_order_id']) is int):
            values['partner_order_id'] = self.resolve_default_booking_contact_id(cr, uid, values['openstc_partner_id'])

        return super(hotel_reservation, self).create(cr, uid, values, context)

    def validate(self, cr, uid, ids, vals, context=None):
        if not isinstance(ids, list):
            ids = [ids]
        wkf_service = netsvc.LocalService('workflow')
        resa_count = 0
        for resa in self.browse(cr, uid, ids, context=context):
            #count to know how many resa have been requested to be confirmed,
            #recurrence is updated to confirmed only if one or more recurrence has been requested to be confirmed
            wkf_service.trg_validate(uid, 'hotel.reservation', resa.id, vals['state'], cr)
            if resa.recurrence_id and resa_count > 0 :
                resa.recurrence_id.write({'recurrence_state':'in_use'})
        return True

    def write(self, cr, uid, ids, vals, context=None):
        if not isinstance(ids,list):
            ids = [ids]
        if context == None:
            context = {}
        self.format_vals(cr, uid, vals, context=context)
        state = None
        if vals.has_key('state_event') :
            state = vals.get('state_event')
            vals[state+'_at'] = datetime.now().strftime('%Y-%m-%d')
            vals.pop('state_event')
        res = super(hotel_reservation, self).write(cr, uid, ids, vals, context)
        if state!= None :
            vals.update( { 'state' : state } )
            self.validate(cr, uid, ids, vals, context)

        return res

    def unlink(self, cr, uid, ids, context=None):
        if not isinstance(ids, list):
            ids = [ids]
        line_ids = []
        for resa in self.browse(cr, uid, ids, context):
            line_ids.extend([x.id for x in resa.reservation_line])
        self.pool.get("hotel_reservation.line").unlink(cr, uid, line_ids, context)
        return super(hotel_reservation, self).unlink(cr, uid, ids, context)

    def onchange_openstc_partner_id(self, cr, uid, ids, openstc_partner_id=False):
        return {'value':{'partner_id':openstc_partner_id}}

    def onchange_partner_shipping_id(self, cr, uid, ids, partner_shipping_id=False):
        email = False
        if partner_shipping_id:
            email = self.pool.get("res.partner.address").browse(cr, uid, partner_shipping_id).email
        return {'value':{'partner_mail':email,'partner_invoice_id':partner_shipping_id,'partner_order_id':partner_shipping_id}}

    def get_nb_prod_reserved(self, cr, prod_list, checkin, checkout, states=['cancel','done','remplir'], where_optionnel=""):
        cr.execute("select reserve_product, sum(qte_reserves) as qte_reservee \
                    from hotel_reservation as hr, \
                    hotel_reservation_line as hrl \
                    where hr.id = hrl.line_id \
                    and reserve_product in %s \
                    and hr.state not in%s \
                    and (hr.checkin, hr.checkout) overlaps ( timestamp %s, timestamp %s ) \
                    " + where_optionnel + " \
                    group by reserve_product; ", (tuple(prod_list), tuple(states), checkin, checkout))
        return cr

    #main method to control availability of products : returns availability of each prod : {prod_id:qty} matching dates
    def get_prods_available_and_qty(self, cr, uid, checkin, checkout, prod_ids=[], where_optionnel='', states=['cancel','done','remplir'], context=None):
        #if no prod_ids put, we check all prods
        if not prod_ids:
            prod_ids = self.pool.get("product.product").search(cr, uid, [])
        prods = self.pool.get("product.product").browse(cr, uid, prod_ids)
        prod_dispo = {}
        #by default, all qty in stock are available
        for prod in prods:
            prod_dispo.setdefault(str(prod.id), prod.virtual_available)
        #and, if some resa are made to this prods, we substract default qty with all qty reserved at these dates
        results = self.get_nb_prod_reserved(cr, prod_ids, checkin, checkout, where_optionnel=where_optionnel,states=states).fetchall()
        for prod_id, qty_reserved in results:
            prod_dispo[str(prod_id)] -= qty_reserved
        return prod_dispo

    """
    @param prod_dict: [{prod_id:id,qty_desired:qty}] a dict mapping prod and corresponding qty desired to check
    @param checkin: str containg begining date of the range of the check
    @param checkout: str containg ending date of the range of the check
    @return: list of dates of unaivalability : [('checkin1','checkout1'),('checkin2','checkout2')]
    @note: to be used in xmlrpc context only
    """
    def get_unaivailable_dates(self, cr, uid, prod_dict, checkin, checkout,context=None):
        #first, get reservation belonging to prod_ids and being in the range (checkin,chekout)
        prod_ids = [item['prod_id'] for item in prod_dict]
        resa_ids = self.search(cr, uid, [('reservation_line.reserve_product.id','in',prod_ids),'|',
                                             '&',('checkin','>=',checkin),('checkin','<=',checkout),
                                             '&',('checkout','>=',checkin),('checkout','<=',checkout)],order='checkin',context=context)
        #i store all checkin - checkout in dates_limit, i order this list,
        #and then, i'll have all dates delimiting (checkin-checkout) checks of qty
        dates_limit = []
        for resa in self.read(cr, uid, resa_ids, ['checkin','checkout']):
            if resa['checkin'] not in dates_limit:
                dates_limit.append(resa['checkin'])
            if resa['checkout'] not in dates_limit:
                dates_limit.append(resa['checkout'])
        dates_limit.sort()
        dates_check = []
        #now, i generate all (checkin-checkout) couple to test
        #for example: dates_limit=[date_a,date_b,date_c] => dates_check=[(date_a,date_b),(dateb,date_c)]
        for i in range(len(dates_limit) - 1):
            dates_check.append((dates_limit[i],dates_limit[i+1]))
        #and i get prod_qty for each date_check,
        #if, for one prod_id, qty is not sufficient, add date_check to the returned value
        ret = []
        for checkin,checkout in dates_check:
            prod_reserved = self.get_prods_available_and_qty(cr, uid, checkin, checkout, prod_ids=prod_ids, context=None)
            for item in prod_dict:
                if item['qty_desired'] > prod_reserved[str(item['prod_id'])]:
                    ret.append((checkin,checkout))
                    #date computed as unavailable, we can skip other prod_id tests for this date
                    break
        return ret

hotel_reservation()

class openresa_reservation_choice(osv.osv):
    _name = "openresa.reservation.choice"

    """
    @param ids: ids of record to compute value
    @return: if all lines are 'dispo' and without 'conflict', returns available
            elif all lines are 'dispo' but if some are 'conflict', returns conflict
            else returns unavailable (some line are not 'dispo')
    @note: can not use fields of hotel.reservation as it, because it changes the checkin-checkout for each choice
    """
    def _get_choice_dispo(self, cr, uid, ids, name, args, context=None):
        #by default, returns available
        ret = {}.fromkeys(ids, 'unavailable')
        return ret

    _columns = {
        'checkin':fields.datetime('Checkin', required=True),
        'checkout':fields.datetime('Checkout', required=True),
        'sequence':fields.integer('Sequence', required=True),
        'state':fields.selection([('waiting','Available choice'),('choosen','Choosen choice'),('refused','Refused choice')]),
        'reservation_id':fields.many2one('hotel.reservation','Reservation'),
        'dispo':fields.function(_get_choice_dispo, type="selection", selection=[('conflict','Conflict'),('unavailable','Unavailable'),('available','Available')], method=True, string="Dispo",),
        }
    _order = "sequence"
    _defaults = {
            'state':lambda *a: 'waiting',
        }
    #override create method to force seconds of dates to '00'
    def create(self, cr, uid, vals, context=None):
        if 'checkin' in vals:
            if len(vals['checkin']) > 16:
                vals['checkin'] = vals['checkin'][0:16] + ':00'
        if 'checkout' in vals:
            if len(vals['checkout']) > 16:
                vals['checkout'] = vals['checkout'][0:16] + ':00'
        return super(openstc_reservation_choice,self).create(cr, uid, vals, context=context)

    #override write method to force seconds of dates to '00'
    def write(self, cr, uid, ids, vals, context=None):
        if 'checkin' in vals:
            if len(vals['checkin']) > 16:
                vals['checkin'] = vals['checkin'][0:16] + ':00'
        if 'checkout' in vals:
            if len(vals['checkout']) > 16:
                vals['checkout'] = vals['checkout'][0:16] + ':00'
        return super(openstc_reservation_choice, self).write(cr, uid, ids, vals, context=context)

openresa_reservation_choice()